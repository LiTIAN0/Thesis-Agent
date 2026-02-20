import os
import re
import difflib
from typing import List, Dict, Any

class RobustCaseStudyReporter:
    """
    Generates academic-grade case study reports with HIGH READABILITY.
    Now includes detailed critic feedback and rationale.
    """

    def __init__(self, output_dir: str = "data/case_studies/lcb"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    @staticmethod
    def extract_code_from_markdown(text: str) -> str:
        if not text: return ""
        # Pattern 1: ```python ... ```
        pattern_python = r"```python\s+(.*?)\s+```"
        match_python = re.search(pattern_python, text, re.DOTALL | re.IGNORECASE)
        if match_python: return match_python.group(1).strip()
        # Pattern 2: ``` ... ```
        pattern_generic = r"```\s+(.*?)\s+```"
        match_generic = re.search(pattern_generic, text, re.DOTALL)
        if match_generic: return match_generic.group(1).strip()
        # Fallback
        if "def " in text or "import " in text: return text.strip()
        return text.strip()

    def _generate_diff(self, code_a: str, code_b: str) -> str:
        diff = difflib.unified_diff(
            code_a.splitlines(), code_b.splitlines(),
            fromfile='Previous', tofile='Refined', lineterm=''
        )
        return "\n".join(list(diff))

    def _format_critiques(self, critiques: List[Any]) -> str:
        """
        Formats the list of critiques into a readable Markdown block.
        Only shows critiques that voted FAIL or flagged SAFETY issues.
        """
        if not critiques:
            return "_No critiques recorded._"

        output = []
        has_issue = False

        for c in critiques:
            # Skip passing critics to reduce noise, unless you want to see them too
            if c.is_passing and not c.safety_violation:
                continue
            
            has_issue = True
            role_icon = "🧠" if "Logic" in c.critic_role else "🎨" if "Style" in c.critic_role else "🛡️"
            
            # Header line
            status = "✅ PASS" if c.is_passing else "❌ FAIL"
            if c.safety_violation:
                status = "🛑 SAFETY VETO"
            
            block = f"**{role_icon} {c.critic_role} Critic** ({status})\n"
            block += f"> {c.feedback}\n"
            output.append(block)

        if not has_issue:
            return "✅ **All Critics Passed** (No specific feedback logs shown)."
        
        return "\n".join(output)

    def save_report(self, task_id: str, prompt: str, history: List[Dict], metrics: Dict) -> str:
        safe_id = task_id.replace("/", "_")
        filename = os.path.join(self.output_dir, f"{safe_id}_analysis.md")

        with open(filename, "w", encoding="utf-8") as f:
            # --- HEADER ---
            f.write(f"# Case Study: {task_id}\n\n")
            
            # --- EXECUTION STATUS (Top Priority) ---
            if "exec_success" in metrics:
                status_icon = "✅" if metrics["exec_success"] else "❌"
                f.write(f"### 🧪 Execution Result: {status_icon}\n")
                if not metrics["exec_success"]:
                    f.write(f"**Error Message:**\n```\n{metrics.get('exec_error', 'Unknown Error')}\n```\n")
                    if metrics.get("agent_claimed_success"):
                         f.write("⚠️ **DISCREPANCY:** Agent voted PASS, but code failed execution. (Potential Hallucination)\n")
            
            f.write(f"\n**Task Prompt:**\n`{prompt[:100]}...` (truncated)\n\n")
            f.write("---\n")

            # --- TIMELINE LOOP ---
            for i in range(len(history)):
                snapshot = history[i]
                current_raw = snapshot.get("draft_code", "")
                current_code = self.extract_code_from_markdown(current_raw)
                
                f.write(f"## 🔄 Iteration {snapshot['iter']}\n\n")

                # 1. Show Code (Diff if not first, else full)
                if i == 0:
                    f.write("### 📝 Initial Draft\n")
                    f.write("```python\n")
                    f.write(current_code)
                    f.write("\n```\n\n")
                else:
                    prev_code = self.extract_code_from_markdown(history[i-1].get("draft_code", ""))
                    diff_text = self._generate_diff(prev_code, current_code)
                    
                    f.write("### 📝 Code Refinement (Diff)\n")
                    if diff_text:
                        f.write("```diff\n")
                        f.write(diff_text)
                        f.write("\n```\n")
                    else:
                        f.write("*No code changes detected.* (Generator ignored feedback?)\n\n")
                    
                    # Optional: Show full code in collapsed section
                    f.write("<details><summary>Click to see full code</summary>\n\n")
                    f.write("```python\n")
                    f.write(current_code)
                    f.write("\n```\n")
                    f.write("</details>\n\n")

                # 2. Show The Feedback that triggered NEXT step (or Final verdict)
                # Note: The feedback stored in snapshot[i] is what resulted FROM snapshot[i]'s code
                
                f.write(f"### 📢 Feedback & Rationale\n")
                
                # A. Critics Detail
                critiques = snapshot.get("critiques", [])
                formatted_critiques = self._format_critiques(critiques)
                f.write(formatted_critiques)
                
                # B. Chairman Summary
                chairman_feedback = snapshot.get("feedback", "")
                if chairman_feedback:
                    f.write(f"\n\n**👨‍⚖️ Chairman's Verdict:**\n")
                    f.write(f"> {chairman_feedback}\n")
                
                f.write("\n---\n")

        return filename