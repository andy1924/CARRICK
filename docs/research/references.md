# Technical references

These primary references support format and platform details. They do not validate performance claims from the supplied research briefs.

| Topic | Reference | Design use |
| --- | --- | --- |
| XER activity and relationship fields | [Oracle XER import/export data map](https://docs.oracle.com/cd/G18294_01/English/Mapping_and_Schema/xer_import_export_data_map_project/xer_import_export_data_map_project.pdf) | Check the fields for activities, WBS links, actual dates, status, and relationships before implementing an adapter. |
| XER import options | [Oracle: Import projects in XER format](https://docs.oracle.com/cd/F51303_01/English/admin/p6_pro_importing_exporting/import_projects_in_xer_format.htm) | Explain why an exported file is not an automatic master-schedule update and why import configuration matters. |
| Out-of-sequence progress | [Oracle: Updating progress](https://docs.oracle.com/cd/E90748_01/English/User_Guides/p6_pro_user/updating_progress.htm) | Treat relationship conflicts as review signals rather than proof that a field event is impossible. |
| Long-running jobs | [FastAPI background task guidance](https://fastapi.tiangolo.com/tutorial/background-tasks/) | Use a separate worker for heavy parsing and inference rather than only in-process background tasks. |
| Lexical candidate retrieval | [PostgreSQL full-text search introduction](https://www.postgresql.org/docs/current/textsearch-intro.html) | Start with a transparent search baseline before adding vector infrastructure. |

## Reference policy

Pin exact library versions when code is added. Verify parser behavior with representative synthetic files and an independent reader. Keep research claims, implementation choices, and measured results in separate sections so a proposal cannot be mistaken for a tested outcome.
