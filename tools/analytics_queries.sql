-- tools/analytics_queries.sql

-- 1. Core cost-efficiency analysis:
--    Compute average latency and cost across different modes
SELECT 
    mode,
    COUNT(task_id) as total_tasks,
    ROUND(AVG(latency_seconds), 2) AS avg_latency,
    ROUND(AVG(cost_usd), 5) AS avg_cost,
    SUM(success) * 100.0 / COUNT(*) AS success_rate_percentage
FROM 
    evaluation_logs
GROUP BY 
    mode
ORDER BY 
    success_rate_percentage DESC;

-- 2. Safety interception analysis:
--    Identify the top 5 anomalous tasks that triggered Safety Veto
--    and incurred the highest cost
SELECT 
    task_id,
    iterations,
    latency_seconds,
    cost_usd
FROM 
    evaluation_logs
WHERE 
    safety_veto = 1
ORDER BY 
    cost_usd DESC
LIMIT 5;

-- 3. Long-tail latency investigation:
--    Find tasks that completed successfully but experienced prolonged
--    local iteration loops (iterations >= 1)
SELECT 
    task_id,
    latency_seconds
FROM 
    evaluation_logs
WHERE 
    success = 1 AND iterations >= 1
ORDER BY 
    latency_seconds DESC;