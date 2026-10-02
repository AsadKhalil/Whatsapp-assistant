import gspread

from app.sheets import Sheets, service_account_email, sheet_error
from app.tools import Caller, lookup_rows, total_rows
from tests.fakes import make_client

STAFF = Caller("staff", False, "Bilal", "923001111111")


class FakeWorksheet:
    def __init__(self, values, col_count=26):
        self.values = values  # first row is the header
        self.col_count = col_count
        self.appended = []
        self.writes = []  # value_input_option of every update and append_rows

    def get_all_records(self):
        head, *body = self.values
        return [dict(zip(head, r)) for r in body]

    def row_values(self, n):
        return self.values[n - 1]

    def append_row(self, row, value_input_option):
        self.appended.append((row, value_input_option))

    def update(self, values, range_name, value_input_option):
        row, col = gspread.utils.a1_to_rowcol(range_name)
        self.values[row - 1][col - 1:] = values[0]
        self.writes.append(value_input_option)

    def add_cols(self, cols):
        self.col_count += cols

    def append_rows(self, values, value_input_option):
        self.values.extend(values)
        self.writes.append(value_input_option)


class FakeBook:
    def __init__(self, tabs):
        self.tabs = tabs
        for title, ws in tabs.items():
            ws.title = title

    def worksheet(self, tab):
        return self.tabs[tab]

    def worksheets(self):
        return list(self.tabs.values())

    def add_worksheet(self, title, rows, cols):
        ws = FakeWorksheet([[]], col_count=cols)
        ws.title = title
        self.tabs[title] = ws
        return ws


class FakeGC:
    def __init__(self, tabs):
        self.book = FakeBook(tabs)
        self.opened = 0

    def open_by_key(self, key):
        self.opened += 1
        return self.book


def test_append_maps_values_by_header_and_stores_raw_text():
    ws = FakeWorksheet([["Item", " Qty ", "Name"]])
    sheets = Sheets(FakeGC({"Orders": ws}))
    sheets.append("sheet-1", "Orders", {"Name": "Ali", "Item": "=IMPORTXML(1)"})
    assert ws.appended == [(["=IMPORTXML(1)", "", "Ali"], "RAW")]


def test_worksheets_are_opened_once():
    gc = FakeGC({"Prices": FakeWorksheet([["Item"], ["Cake"]])})
    sheets = Sheets(gc)
    assert sheets.rows("s", "Prices") == [{"Item": "Cake"}]
    sheets.rows("s", "Prices")
    assert gc.opened == 1


def test_knowledge_is_rendered_without_blanks_and_cached():
    ws = FakeWorksheet([["Question", "Answer"], ["Delivery?", "Free above 3000"], ["", ""]])
    sheets = Sheets(FakeGC({"Knowledge": ws}))
    assert sheets.knowledge("s", "Knowledge", now=0) == "Question: Delivery? | Answer: Free above 3000"
    ws.values.append(["Hours?", "9 to 5"])
    assert "Hours" not in sheets.knowledge("s", "Knowledge", now=100)
    assert "Hours" in sheets.knowledge("s", "Knowledge", now=400)


def test_headers_are_trimmed_and_cached():
    ws = FakeWorksheet([["Item ", "Price"]])
    sheets = Sheets(FakeGC({"Prices": ws}))
    assert sheets.headers("s", "Prices", now=0) == ["Item", "Price"]
    ws.values[0] = ["Changed"]
    assert sheets.headers("s", "Prices", now=10) == ["Item", "Price"]


def test_header_with_a_stray_space_still_lets_a_customer_find_their_own_row():
    ws = FakeWorksheet([["Phone ", "Item"], ["923001234567", "Cake"]])
    sheets = Sheets(FakeGC({"Orders": ws}))
    caller = Caller("customer", False, "Ali", "923001234567")
    r = lookup_rows(sheets, make_client(), caller, "Orders", "")
    assert r["rows"] == [{"Phone": "923001234567", "Item": "Cake"}]


def test_blank_middle_rows_are_dropped_before_counting():
    ws = FakeWorksheet([["Date", "Amount"], ["2026-06-01", "100"], ["", ""], ["2026-06-02", "200"]])
    sheets = Sheets(FakeGC({"Expenses": ws}))
    r = total_rows(sheets, make_client(), STAFF, "Expenses", sum_column="Amount")
    assert r["rows_counted"] == 2 and r["total"] == 300
    assert r["skipped"] == {"unreadable_date": 0, "unreadable_number": 0}


def test_tab_headers_list_every_tab_with_its_trimmed_header_row():
    sheets = Sheets(FakeGC({"Prices": FakeWorksheet([["Item ", "Price"]]), "Empty": FakeWorksheet([[]])}))
    assert sheets.tab_headers("s") == {"Prices": ["Item", "Price"], "Empty": []}


def test_a_new_tab_gets_its_header_row_as_typed():
    gc = FakeGC({})
    Sheets(gc).add_tab("s", "Orders", ["Date", "=Name"])
    ws = gc.book.tabs["Orders"]
    assert ws.values == [["Date", "=Name"]] and ws.writes == ["RAW"] and ws.col_count == 26


def test_new_columns_go_after_the_last_header_cell_widening_the_tab():
    ws = FakeWorksheet([["Date", "", "Item"], ["2026-06-01", "x", "Cake"]], col_count=4)
    sheets = Sheets(FakeGC({"Orders": ws}))
    assert sheets.headers("s", "Orders", now=0) == ["Date", "", "Item"]
    sheets.add_columns("s", "Orders", ["Status", "=Notes"])
    assert ws.values == [["Date", "", "Item", "Status", "=Notes"], ["2026-06-01", "x", "Cake"]]
    assert ws.col_count == 5 and ws.writes == ["RAW"]
    assert sheets.headers("s", "Orders", now=1) == ["Date", "", "Item", "Status", "=Notes"]  # cache dropped


def test_knowledge_rows_go_in_one_call_matched_by_header_ignoring_case():
    ws = FakeWorksheet([["question", "Answer "], ["Hours?", "9-5"]])
    sheets = Sheets(FakeGC({"Knowledge": ws}))
    assert "Lahore" not in sheets.knowledge("s", "Knowledge", now=0)
    sheets.append_rows("s", "Knowledge", [{"Question": "=1+1", "Answer": "Two"},
                                          {"Question": "Where?", "Answer": "Lahore"}])
    assert ws.values[2:] == [["=1+1", "Two"], ["Where?", "Lahore"]] and ws.writes == ["RAW"]
    assert "Lahore" in sheets.knowledge("s", "Knowledge", now=1)  # cache dropped


def test_service_account_email_and_friendly_sheet_errors(tmp_path):
    key = tmp_path / "key.json"
    key.write_text('{"client_email": "bot@proj.iam.gserviceaccount.com"}', encoding="utf-8")
    email = service_account_email(str(key))
    assert email == "bot@proj.iam.gserviceaccount.com"
    assert service_account_email(str(tmp_path / "missing.json")) == ""
    assert "isn't shared with bot@proj" in sheet_error(gspread.exceptions.SpreadsheetNotFound(), email)

    class Forbidden(Exception):
        code = 403

    assert sheet_error(Forbidden(), email) == "Share the Sheet with bot@proj.iam.gserviceaccount.com as Editor."
    assert sheet_error(gspread.exceptions.WorksheetNotFound("Orders"), email) == "Tab 'Orders' is not in the Sheet."
    assert "couldn't be reached" in sheet_error(RuntimeError("down"), "")
    assert "the service account" in sheet_error(gspread.exceptions.SpreadsheetNotFound(), "")
