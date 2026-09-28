SELECT
    name AS issue,
    subject,
    status,
    synthetic_reference,
    owner,
    modified
FROM `tabIssue`
ORDER BY modified DESC
