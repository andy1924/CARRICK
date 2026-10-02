# Web application

Responsive local interface for supervisor reporting and planner review. It currently uses plain JavaScript, HTML, and CSS so the prototype runs without a frontend build step.

The introduction at `/` explains the product through an interactive workflow and a read-only field-note preview against a synthetic schedule. The working application is at `/app`.

Current screens: report composer, schedule import, activity search, review queue, event history, and export summary. The report composer can use grounded AI matching when configured, and the review queue accepts a short clarification to refine an AI suggestion. Text, email, and selectable-text PDF reports can be imported. The UI distinguishes staged, approved, rejected, and exported states.

See [product requirements](../../docs/product/requirements.md) and [API outline](../../docs/architecture/api.md).

The website and workspace share slate, white, and blue styling with system fonts. The introduction contains an interactive capture/match/review tour using synthetic data. Workspace screens support direct links, mobile navigation, candidate selection, and searchable progress history. See [design research and decisions](../../docs/design/website-redesign.md).
