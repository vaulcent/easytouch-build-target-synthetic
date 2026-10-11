// Copyright (c) 2026, Easytouch Test and contributors
// Salesperson Sales Summary - Query Report client filters.
//
// Supplies the selected date range (from_date / to_date) that the adjacent
// salesperson_sales_summary.sql file binds as %(from_date)s / %(to_date)s.

frappe.query_reports["Salesperson Sales Summary"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
	],
};
