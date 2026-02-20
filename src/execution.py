import sys
import ast
import threading
import queue
import json
import math
import collections
import itertools
import heapq
import bisect
import re
import io
import contextlib
import inspect
import unicodedata

# ==========================================
# Shared Utilities
# ==========================================

class TimeoutException(Exception): pass

def clean_code_string(code: str) -> str:
    """
    Robustly clean Python code from LLM artifacts and weird Unicode characters.
    Improvements:
    - Unicode normalize (NFKC)
    - Extract code blocks from Markdown
    - Replace many smart quotes, spaces, dashes
    - Replace any Unicode dash punctuation (category 'Pd') with ASCII hyphen-minus '-'
    - Replace mathematical minus sign U+2212 with '-'
    - Remove control characters except newline/tab/carriage-return
    """
    if not isinstance(code, str):
        return code

    # 1) Normalize unicode
    code = unicodedata.normalize("NFKC", code)

    # 2) Extract from triple-backtick blocks if present (supports ```python and ```)
    pattern = r"```(?:python)?\s*(.*?)\s*```"
    m = re.search(pattern, code, re.DOTALL | re.IGNORECASE)
    if m:
        code = m.group(1)

    # 3) Common replacements map (keeps ASCII equivalents)
    replacements = {
        '\xa0': ' ',       # NBSP
        '\u2000': ' ',     # en quad
        '\u2001': ' ',     # em quad
        '\u2002': ' ',     # en space
        '\u2003': ' ',     # em space
        '\u2004': ' ',     # three-per-em space
        '\u2005': ' ',     # four-per-em space
        '\u2006': ' ',     # six-per-em space
        '\u2007': ' ',     # figure space
        '\u2008': ' ',     # punctuation space
        '\u2009': ' ',     # thin space
        '\u200a': ' ',     # hair space
        '\u200b': '',      # zero width space
        '\u200c': '',      # zero width non-joiner
        '\u200d': '',      # zero width joiner
        '\ufeff': '',      # BOM
        '“': '"', '”': '"',
        "‘": "'", "’": "'",
        '…': '...', '×': '*', '÷': '/',
        '≤': '<=', '≥': '>=', '≠': '!=',
        # common dash replacements (these will also be handled by Pd mapping below)
        '–': '-', '—': '-', '―': '-',  # en-dash, em-dash, horizontal bar
        # bullets / list markers often introduced by LLMs
        '·': '', '•': '', '●': '', '▪': '-', '▫': '-', '⁃': '-', '⁎': '*',
    }
    for old, new in replacements.items():
        code = code.replace(old, new)

    # 4) Replace mathematical minus sign U+2212 with ASCII hyphen-minus
    code = code.replace('\u2212', '-')

    # 5) Replace line/paragraph separators with newline
    code = code.replace('\u2028', '\n').replace('\u2029', '\n')

    # 6) Replace any dash punctuation (Unicode category 'Pd') with ASCII hyphen-minus
    #    This covers U+2010, U+2011, U+2012, etc.
    result_chars = []
    for ch in code:
        try:
            cat = unicodedata.category(ch)
        except Exception:
            cat = ''
        if cat == 'Pd':
            result_chars.append('-')
        else:
            result_chars.append(ch)
    code = ''.join(result_chars)

    # 7) Remove control characters (category Cc and Cf) except keep \n, \t, \r
    cleaned_chars = []
    for ch in code:
        cat = unicodedata.category(ch)
        if cat.startswith('C'):
            if ch in ('\n', '\t', '\r'):
                cleaned_chars.append(ch)
            else:
                continue
        else:
            cleaned_chars.append(ch)
    code = ''.join(cleaned_chars)

    # 8) Strip trailing carriage returns converted weirdly: normalize CRLF -> LF
    code = code.replace('\r\n', '\n').replace('\r', '\n')

    # 9) Trim surrounding whitespace
    return code.strip()

def extract_code_from_markdown(text: str) -> str:
    return clean_code_string(text)

# ==========================================
# LiveCodeBench Executor (V5.3 - Unicode + diagnostics)
# ==========================================

def parse_lcb_input(input_str: str):
    """
    Smart parsing for LCB inputs.

    - If input contains newlines, split lines and parse each line separately.
    - Attempt JSON parsing for each piece first, then fallback to Python eval,
      otherwise return the raw string when parsing fails.
    - Returns a single value or a tuple of values depending on the content.
    """
    if input_str is None:
        return None

    # Keep original raw for potential stdin feeding; but parsing uses stripped version.
    raw = input_str
    input_str = input_str.strip()

    eval_context = {
        "true": True, "false": False, "null": None,
        "math": math, "inf": float('inf')
    }

    def try_parse_piece(piece: str):
        p = piece.strip()
        if not p:
            return None
        # Try JSON first (safe for lists, dicts, numbers, strings)
        try:
            return json.loads(p)
        except Exception:
            pass
        # Then Python eval (allows tuples, single ints, etc.)
        try:
            # Force tuple if comma exists and not a JSON start
            if "," in p and not (p.startswith("[") or p.startswith("{")):
                return eval(f"({p})", eval_context)
            else:
                return eval(p, eval_context)
        except Exception:
            # fallback: raw string (return the original piece, not the stripped raw to preserve spacing)
            return piece

    # If multi-line, always parse each non-empty line
    if "\n" in input_str:
        parts = [line for line in (l.strip() for l in input_str.splitlines()) if line]
        parsed_parts = [try_parse_piece(part) for part in parts]
        if len(parsed_parts) == 0:
            return ""
        if len(parsed_parts) == 1:
            return parsed_parts[0]
        return tuple(parsed_parts)

    # Single-line: try JSON (covers arrays and objects), then Python eval, then fallback string
    try:
        return json.loads(input_str)
    except Exception:
        pass

    try:
        # Force tuple if comma exists and not starting with JSON-style braces
        if "," in input_str and not (input_str.startswith("[") or input_str.startswith("{")):
            return eval(f"({input_str})", eval_context)
        else:
            return eval(input_str, eval_context)
    except Exception:
        return input_str

def flexible_equal(a, b):
    """Loose equality check."""
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-5)
    
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b): return False
        return all(flexible_equal(x, y) for x, y in zip(a, b))
    
    return a == b

def try_parse_printed_output(s: str):
    """
    Try to interpret printed output string as a structured value similar to input parsing.
    Falls back to the raw stripped string if parsing fails.
    """
    s = s.strip()
    if not s:
        return None
    try:
        return parse_lcb_input(s)
    except Exception:
        return s

def execute_lcb_code(code_raw: str, test_cases: list, entry_point: str = None) -> tuple[bool, str]:
    """
    Executes LCB code using inspect.signature.bind() to resolve argument mismatches.
    Supports zero-arg 'solve()' functions by piping the raw test input into stdin.
    """
    # 1. Clean Code
    code = clean_code_string(code_raw)
    if not code:
        return False, "Empty code"

    # 2. Syntax Check
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax Error: {e}"

    # 3. Find Entry Point
    if not entry_point:
        top_functions = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
        if not top_functions:
            return False, "No function found"
        candidates = [f for f in top_functions if f.lower() in [
            'solution', 'solve', 'countgoodintegers', 'max_bitwise_or',
            'max_bitwise_or_after_k_operations'
        ]]
        entry_point = candidates[-1] if candidates else top_functions[-1]

    # 4. Prepare Environment
    global_scope = {}
    try:
        exec("import math\nimport collections\nimport itertools\nimport re\nimport heapq\nimport bisect\nfrom typing import *", global_scope)
        exec(code, global_scope)
        func = global_scope.get(entry_point)
        if not func:
            return False, f"Function '{entry_point}' not found"

        # --- Obtain function signature ---
        try:
            sig = inspect.signature(func)
        except ValueError:
            sig = None

        # --- Internal Runner ---
        def run_once(args, raw_input_str):
            """
            args: parsed argument(s)
            raw_input_str: original raw input string for feeding stdin when needed
            """
            result_queue = queue.Queue()
            
            def target():
                try:
                    final_call_args = None
                    final_call_kwargs = {}
                    unpack = False

                    def can_bind_positional(candidate):
                        try:
                            sig.bind(*candidate)
                            return True
                        except Exception:
                            return False

                    def can_bind_single(obj):
                        try:
                            sig.bind(obj)
                            return True
                        except Exception:
                            return False

                    # Special case: function expects zero arguments -> call with no args
                    if sig is not None and len(sig.parameters) == 0:
                        old_stdin = sys.stdin
                        try:
                            stdin_buf = io.StringIO(raw_input_str if raw_input_str is not None else "")
                            sys.stdin = stdin_buf
                            out_buf = io.StringIO()
                            with contextlib.redirect_stdout(out_buf):
                                res = func()
                            printed = out_buf.getvalue().strip()
                            if res is None and printed != "":
                                try:
                                    res = try_parse_printed_output(printed)
                                except Exception:
                                    res = printed
                        finally:
                            sys.stdin = old_stdin
                        result_queue.put(("success", res))
                        return

                    # If args is a dict -> try kwargs first
                    if sig and isinstance(args, dict):
                        try:
                            sig.bind(**args)
                            final_call_kwargs = args
                            unpack = False
                        except Exception:
                            pass

                    if sig:
                        # Ordered attempts when signature is available
                        if isinstance(args, (list, tuple)):
                            if can_bind_positional(args):
                                final_call_args = tuple(args)
                                unpack = True
                            elif len(args) == 1 and isinstance(args[0], (list, tuple)) and can_bind_positional(args[0]):
                                final_call_args = tuple(args[0])
                                unpack = True
                            elif can_bind_single(args):
                                final_call_args = (args,)
                                unpack = False
                            else:
                                pos_param_count = len([p for p in sig.parameters.values()
                                                      if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)])
                                if isinstance(args, (list, tuple)) and len(args) == pos_param_count:
                                    final_call_args = tuple(args)
                                    unpack = True
                        else:
                            if can_bind_single(args):
                                final_call_args = (args,)
                                unpack = False
                    else:
                        # No signature available
                        if isinstance(args, (list, tuple)):
                            final_call_args = tuple(args)
                            unpack = True
                        elif isinstance(args, dict):
                            final_call_kwargs = args
                            unpack = False
                        else:
                            final_call_args = (args,)
                            unpack = False

                    # === EXECUTION ===
                    if final_call_kwargs:
                        res = func(**final_call_kwargs)
                    elif final_call_args is not None:
                        if unpack:
                            try:
                                res = func(*final_call_args)
                            except TypeError:
                                res = func(final_call_args)
                        else:
                            try:
                                if len(final_call_args) == 1:
                                    res = func(final_call_args[0])
                                else:
                                    res = func(*final_call_args)
                            except TypeError:
                                res = func(*final_call_args)
                    else:
                        res = func(args)

                    result_queue.put(("success", res))
                    
                except Exception as e:
                    # Provide helpful diagnostic but do not attempt to change user code semantics
                    try:
                        param_names = list(sig.parameters.keys()) if sig else []
                    except Exception:
                        param_names = []
                    diag = RuntimeError(f"Execution failed. Error: {e}. Args repr: {repr(args)}. Params: {param_names}")
                    result_queue.put(("error", diag))

            t = threading.Thread(target=target)
            t.daemon = True
            t.start()
            t.join(2) # 2 seconds timeout

            if t.is_alive(): raise TimeoutException("Timeout")
            if result_queue.empty(): raise TimeoutException("No result returned")
            
            status, val = result_queue.get()
            if status == "error":
                if isinstance(val, str): raise RuntimeError(val)
                raise val
            return val

        # 5. Run Test Cases
        for i, case in enumerate(test_cases):
            input_raw = case.get('input')
            output_raw = case.get('output')
            
            try:
                args = parse_lcb_input(input_raw)
                expected = parse_lcb_input(output_raw)
                
                result = run_once(args, input_raw)
                
                if not flexible_equal(result, expected):
                    return False, f"Test {i+1} Failed. Expected {expected}, Got {result}. Input: {input_raw}"
                    
            except TimeoutException:
                return False, f"Timeout on Test {i+1}"
            except Exception as e:
                return False, f"Runtime Error on Test {i+1}: {e}"

    except Exception as e:
        return False, f"Setup Error: {e}"

    return True, "Passed"

# ==========================================
# Legacy Support
# ==========================================
def execute_humaneval_code(code: str, test_case: str, entry_point: str, timeout: int = 3):
    full_code = f"{code}\n\n{test_case}\ncheck({entry_point})"
    f = io.StringIO()
    import signal
    has_alarm = hasattr(signal, "SIGALRM")
    if has_alarm:
        def handler(signum, frame): raise TimeoutException("Execution Timed Out")
        signal.signal(signal.SIGALRM, handler)
        signal.alarm(timeout)
    try:
        with contextlib.redirect_stdout(f):
            exec(full_code, {'__name__': '__main__'})
        if has_alarm: signal.alarm(0)
        return True, "Passed"
    except Exception as e:
        if has_alarm: signal.alarm(0)
        return False, f"Runtime Error: {str(e)}"
