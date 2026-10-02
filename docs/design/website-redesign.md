# Website and workspace design

The October 2026 redesign uses a shared visual system for the public introduction and project workspace. Its purpose is to explain Carrick's field reporting workflow clearly and make daily capture and review easier to navigate.

## Research

The research considered first-party product pages and published design notes:

- [Linear's interface refresh](https://linear.app/now/behind-the-latest-design-refresh) describes prioritizing the user's task, reducing the weight of navigation, compacting controls, and softening unnecessary separation.
- [Linear's product website](https://linear.app/) demonstrates its workflow through detailed interface examples rather than relying only on abstract feature descriptions.
- [Ashby's platform](https://www.ashbyhq.com/platform/recruiting/ats) groups capabilities around concrete tasks and shows how the product supports each stage of a professional workflow.
- [Procore's project management page](https://www.procore.com/project-management) organizes its story around field productivity, workflow efficiency, document control, and schedule coordination.

These are design references, not customer relationships or claims about Carrick. The implementation uses original layouts, SVG assets, and copy.

## Decisions

| Area | Decision | User benefit |
| --- | --- | --- |
| Product story | Lead with field reports linked to schedule activities | A visitor can identify the audience and purpose immediately |
| Hero demonstration | Show source evidence, activity context, dates, and review together | The interface explains the handoff concretely |
| Product tour | Capture, match, and review tabs; three examples; custom note preview | Visitors can explore the workflow at their own pace |
| Typography | System sans-serif stack, compact application headings, larger marketing headings | Readable hierarchy without downloading external fonts |
| Palette | White surfaces, slate text, blue actions | Consistent hierarchy across website and workspace |
| Navigation | Persistent desktop sidebar, controlled mobile drawer, links to application views | Users can move directly to the task they need |
| Review | Visible candidate choices alongside the original report | Planners can compare suggested activities without opening a dropdown first |
| History | Search by report or activity ID and filter by review status | Users can find relevant records quickly |
| Copy | Explain actual capabilities and practical next steps | Product language stays useful and verifiable |
| Motion | Short state transitions with reduced-motion support | Feedback supports interaction without distracting from work |

## Product boundaries in the copy

The website describes XER/CSV import, uploaded reports, optional cloud or local AI matching, planner decisions, and approved progress CSV export. Scan OCR and handwriting transcription now have optional local adapters with editable previews; microphone capture, offline reports, and schedule scenarios are implemented in the workspace. Native schedule output and direct P6 synchronization remain future capabilities. The tour uses synthetic data and does not store submitted notes or planner decisions. It contains no invented customers, testimonials, performance figures, certifications, or pricing.

## Interface behavior

The product tour starts in review so the source-to-activity connection is visible immediately. Example report selection resets the sample decision. Custom notes use the existing read-only preview endpoint; cancellation prevents an older response from replacing a newly selected example.

Workspace navigation preserves the selected view in the URL. On mobile, the navigation drawer closes after selection and on Escape, with hidden navigation excluded from keyboard interaction. Pending processing states prevent repeat submissions. Candidate radio choices and the full activity selector stay synchronized. Every approval still uses the existing server validation.


## Workspace recovery and interaction reliability

The workspace now keeps its last usable data during refreshes and shows a persistent loading/error panel with an explicit retry. Missing data displays placeholders rather than zero counts or an empty project. Overlapping refreshes are cancelled so older responses cannot replace newer ones. Approvals and exports pause while schedule data is stale.

Review selections, dates, clarification text, and planner notes survive background updates. Actual approval remains disabled until activity/date checks succeed and required warning notes are present. Failed checks offer an inline retry; decisions and exports remain locked while saving. Report fields are temporarily locked during submission to prevent new edits being cleared by the response.

Errors stay visible until dismissed. History and scenario requests provide retry controls while retaining previous results with a stale-result explanation. Sign-in can retry a failed connection and ignores malformed remembered context. Restricted browser storage does not block online sign-in. Reconnection preserves the current choice of standard/AI matching. Header controls wrap on narrow screens.

Browser regression coverage includes failed initial loads, preserved review edits, validation failure/retry, connection recovery at sign-in, and submission locks. Existing import, capture, approval, export, and offline workflows remain covered.
