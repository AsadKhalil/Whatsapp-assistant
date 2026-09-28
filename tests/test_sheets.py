from app.sheets import Sheets
from app.tools import Caller, lookup_rows, total_rows
from tests.fakes import make_client

STAFF = Caller("staff", False, "Bilal", "923001111111")


class FakeWorksheet:
    def __init__(self, values):
        self.values = values  # first row is the header
        self.appended = []

    def get_all_records(self):
        head, *body = self.values
        return [dict(zip(head, r)) for r in body]

    def row_values(self, n):
        return self.values[n - 1]

    def append_row(self, row, value_input_option):
        self.appended.append((row, value_input_option))


class FakeBook:
    def __init__(self, tabs):
        self.tabs = tabs

    def worksheet(self, tab):
        return self.tabs[tab]


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
