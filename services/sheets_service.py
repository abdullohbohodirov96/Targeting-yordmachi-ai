class SheetsService:
    def __init__(self, credentials_path: str = None, sheet_id: str = None):
        self.credentials_path = credentials_path
        self.sheet_id = sheet_id

    async def append_row(self, data: list):
        """
        Adds a row to the Google Sheet.
        Placeholder for real Google Sheets API connection.
        """
        pass
