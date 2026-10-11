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
INNER JOIN (
    SELECT
        parent AS invoice,
        sales_person,
        allocated_percentage
    FROM `tabSales Team`
    WHERE parenttype = 'Sales Invoice'
) stc ON stc.invoice = si.name
LEFT JOIN (
    SELECT
        parent AS invoice,
        SUM(base_net_amount - (incoming_rate * qty)) AS profit
    FROM `tabSales Invoice Item`
    GROUP BY parent
) ip ON ip.invoice = si.name
WHERE si.docstatus = 1
    AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
GROUP BY stc.sales_person
ORDER BY total_sales DESC
