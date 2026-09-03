# Audit learning log

Add only portable, anonymized lessons. Do not include company, customer, repository, account, or secret details.

| Condition | Failure mode | Detection | Safe default | Evidence date |
| --- | --- | --- | --- | --- |
| Moving a large active workspace on Windows | A move may copy some children but fail to remove locked or protected source children, leaving unresolved duplicates. | Compare source and destination names and counts immediately after the move. | Preserve both copies; do not delete or merge until locks are released and authoritative content is compared. | 2026-08-21 |
