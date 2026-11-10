# Grouped purchase confirmation — 4 November 2026

For a resolved supplier, the existing task card now collects unresolved bill status,
delivery status, received date and rate basis together. Saved situation facts and
known rates are omitted. Missing actual line rates have explicit numeric inputs.
One submission sends the selected facts as a single source message through the
existing task revision/grounding and preview pipeline. Date and tax basis are never
preselected; submission is not posting approval.

UI regression verifies all three choices are grouped, no defaults are chosen,
date is blank, known rate is not asked again, and one submit carries the combined
facts. Connector/proposal and chat refresh suites pass. Asset version is 47.
Fresh visual browser acceptance and native posting are not claimed.
