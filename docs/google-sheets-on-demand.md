# On-demand Google Sheets integration

Google Sheets is write-on-demand only. Normal LINE/Slack requests do not write to Sheets.

## Required Render environment variables

- `GOOGLE_SHEETS_SPREADSHEET_ID`: target spreadsheet ID.
- `GOOGLE_SHEETS_WORKSHEET_RANGE`: append range, for example `Jobs!A:Z`.
- `GOOGLE_SHEETS_CREDENTIALS_JSON_B64`: base64-encoded Google service-account JSON.

`GOOGLE_APPLICATION_CREDENTIALS` is also supported when a credential file is available.

## Safety behavior

- The Sheets tool is exposed as `append_google_sheets`.
- The tool is only accepted when the original user message explicitly mentions Google Sheets/spreadsheet and an action such as 反映・記録・追加・書き込み.
- Negative requests such as 反映しない / 不要 are rejected.
- Credentials are read from environment variables and are never committed to the repository.
- Data is appended using the official Sheets API `spreadsheets.values.append` operation.

## Example

Send from LINE or Slack:

「AIエンジニアの求人を検索して、Google Sheetsに反映してください。会社名、求人名、勤務地、年収、URL、取得日時を記録してください。」

The normal agent flow can search and structure the jobs, then call `append_google_sheets` only because the request explicitly asked for the Sheets write.

Before production use, share the target spreadsheet with the service-account email and configure the Render environment variables. Do not put the service-account JSON in Git.
