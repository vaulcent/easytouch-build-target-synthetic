-- Salesperson Sales Summary (Query Report)
--
-- For each Salesperson (Sales Team child row on a submitted Sales Invoice)
-- within the selected posting_date range: total sales, collected amount,
-- outstanding amount, gross profit, and the number of distinct customers
-- they sold to.
--
-- Required report filters (passed as %(from_date)s / %(to_date)s):
--   from_date, to_date
--
-- `name` below is deliberately left as the unqualified, portable row
-- identifier (`name AS issue`): after the two CTEs below rename their own
-- `name` column to `invoice`, `tabSales Invoice`.`name` is the only
-- remaining `name` column reachable from the outer SELECT, so this stays
-- unambiguous while still being explicit and read-only (no mutation of the
-- underlying `name` column).
WITH sales_team_rows AS (
    SELECT
        parent AS invoice,
        sales_person,
        allocated_percentage
    FROM `tabSales Team`
    WHERE parenttype = 'Sales Invoice'
),
invoice_profit AS (
    SELECT
        parent AS invoice,
        SUM(base_net_amount - (incoming_rate * qty)) AS profit
    FROM `tabSales Invoice Item`
    GROUP BY parent
)
SELECT
    stc.sales_person AS salesperson,
    SUM(si.base_grand_total * stc.allocated_percentage / 100) AS total_sales,
    SUM(
        (si.base_grand_total - si.outstanding_amount)
        * stc.allocated_percentage / 100
    ) AS collected_amount,
    SUM(si.outstanding_amount * stc.allocated_percentage / 100) AS outstanding_amount,
    SUM(COALESCE(ip.profit, 0) * stc.allocated_percentage / 100) AS gross_profit,
    COUNT(DISTINCT si.customer) AS number_of_customers,
    name AS issue
FROM `tabSales Invoice` si
INNER JOIN sales_team_rows stc ON stc.invoice = si.name
LEFT JOIN invoice_profit ip ON ip.invoice = si.name
WHERE si.docstatus = 1
    AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
GROUP BY stc.sales_person
ORDER BY total_sales DESC
