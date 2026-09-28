from app.tools import Caller, build_row, can, describe_tabs, lookup_rows, proposal_text, saved_text, total_rows
from tests.fakes import bakery_sheets, make_client

ALI = "923001234567"
CUSTOMER = Caller("customer", False, "Ali", ALI)
HIDDEN = Caller("customer", False, "Ali", None)
GROUP_CUSTOMER = Caller("customer", True, "Ali", ALI)
STAFF = Caller("staff", False, "Bilal", "923001111111")


def test_customer_reads_a_public_tab_with_word_search():
    r = lookup_rows(bakery_sheets(), make_client(), CUSTOMER, "Prices", "Chocolate CAKE")
    assert [row["Item"] for row in r["rows"]] == ["Chocolate cake"]


def test_customer_sees_only_own_orders_whatever_the_phone_format():
    r = lookup_rows(bakery_sheets(), make_client(), CUSTOMER, "Orders", "")
    assert [row["Name"] for row in r["rows"]] == ["Ali"]


def test_hidden_phone_cannot_read_own_rows():
    assert "hidden" in lookup_rows(bakery_sheets(), make_client(), HIDDEN, "Orders", "")["error"]


def test_customer_cannot_read_staff_or_unknown_tabs():
    sheets, client = bakery_sheets(), make_client()
    assert "not available" in lookup_rows(sheets, client, CUSTOMER, "Staff Notes", "")["error"]
    assert "Unknown tab" in lookup_rows(sheets, client, CUSTOMER, "Salaries", "")["error"]


def test_customer_in_a_group_gets_public_tabs_only():
    sheets, client = bakery_sheets(), make_client()
    assert lookup_rows(sheets, client, GROUP_CUSTOMER, "Prices", "")["rows"]
    assert "private chat" in lookup_rows(sheets, client, GROUP_CUSTOMER, "Orders", "")["error"]
    assert "private chat" in build_row(sheets, client, GROUP_CUSTOMER, "Orders",
                                       [{"column": "Item", "value": "Cake"}])["error"]


def test_staff_reads_everything():
    assert len(lookup_rows(bakery_sheets(), make_client(), STAFF, "Orders", "cake")["rows"]) == 2


def test_rows_are_capped_at_20():
    sheets = bakery_sheets()
    sheets.tabs["Prices"] = [{"Item": f"Cake {i}", "Price": i} for i in range(25)]
    r = lookup_rows(sheets, make_client(), CUSTOMER, "Prices", "cake")
    assert len(r["rows"]) == 20 and r["more"] == 5


def test_customer_row_takes_name_and_phone_from_whatsapp_not_the_model():
    r = build_row(bakery_sheets(), make_client(), CUSTOMER, "Orders",
                  [{"column": "Item", "value": "Carrot cake"}, {"column": "Phone", "value": "0000000000"}])
    assert r["row"] == {"Item": "Carrot cake", "Phone": ALI, "Name": "Ali"}


def test_hidden_phone_customer_must_type_a_number():
    sheets, client = bakery_sheets(), make_client()
    assert "hidden" in build_row(sheets, client, HIDDEN, "Orders", [{"column": "Item", "value": "Cake"}])["error"]
    ok = build_row(sheets, client, HIDDEN, "Orders",
                   [{"column": "Item", "value": "Cake"}, {"column": "Phone", "value": "0300 1234567"}])
    assert ok["row"]["Phone"] == "0300 1234567"


def test_staff_rows_keep_model_values_and_bad_input_is_rejected():
    sheets, client = bakery_sheets(), make_client()
    r = build_row(sheets, client, STAFF, "Orders",
                  [{"column": "Name", "value": "Sana"}, {"column": "Phone", "value": "0321 7654321"}])
    assert r["row"] == {"Name": "Sana", "Phone": "0321 7654321"}
    assert "Unknown column" in build_row(sheets, client, STAFF, "Orders",
                                         [{"column": "Colour", "value": "red"}])["error"]
    assert "No values" in build_row(sheets, client, CUSTOMER, "Orders", ["two cakes", 3])["error"]
    assert "can't be added" in build_row(sheets, client, CUSTOMER, "Prices",
                                         [{"column": "Item", "value": "x"}])["error"]


def test_permissions_shape_the_prompt():
    client, sheets = make_client(), bakery_sheets()
    assert can(client, STAFF, "Staff Notes", "read") and not can(client, CUSTOMER, "Staff Notes", "read")
    text = describe_tabs(client, CUSTOMER, sheets)
    assert "- Prices (columns: Item, Price): look up and total rows" in text
    assert "look up and total this customer's own rows, propose new rows" in text
    assert "Staff Notes" not in text and "Expenses" not in text
    assert "Orders" not in describe_tabs(client, GROUP_CUSTOMER, sheets)
    assert "- Expenses (columns: Date, Item, Amount, Category): look up and total rows, add rows" in describe_tabs(
        client, STAFF, sheets)


def test_proposal_and_saved_texts_list_the_values():
    row = {"Item": "Cake", "Qty": "2"}
    assert proposal_text("Orders", row) == "Add to Orders:\n• Item: Cake\n• Qty: 2\n\nReply YES to confirm or NO to cancel."
    assert saved_text("Orders", row) == "✅ Saved to Orders:\n• Item: Cake\n• Qty: 2"


# Review focus: totals over messy, hand-edited Sheet data must be right, and unreadable rows reported.
def test_totals_are_computed_in_code_by_date_and_category():
    r = total_rows(bakery_sheets(), make_client(), STAFF, "Expenses", date_column="Date", from_date="2026-06-01",
                   to_date="2026-06-30", sum_column="Amount", group_by="Category")
    assert r == {"tab": "Expenses", "rows_counted": 3, "skipped": {"unreadable_date": 1, "unreadable_number": 1},
                 "total": 27300, "by": {"Rent": {"rows": 1, "total": 25000}, "Transport": {"rows": 2, "total": 2300}}}


def test_totals_can_just_count_and_follow_row_visibility():
    sheets, client = bakery_sheets(), make_client()
    petrol = total_rows(sheets, client, STAFF, "Expenses", match="petrol")
    assert petrol["rows_counted"] == 2 and "total" not in petrol
    cakes = total_rows(sheets, client, STAFF, "Orders", date_column="Date", from_date="2026-09-01",
                       to_date="2026-09-30", sum_column="Qty", match="cake")
    assert (cakes["rows_counted"], cakes["total"]) == (2, 3)
    own = total_rows(sheets, client, CUSTOMER, "Orders", sum_column="Qty")
    assert (own["rows_counted"], own["total"]) == (1, 1)  # only Ali's order
    assert "not available" in total_rows(sheets, client, CUSTOMER, "Expenses", sum_column="Amount")["error"]


def test_totals_reject_bad_inputs():
    sheets, client = bakery_sheets(), make_client()
    assert "2026-06-30" in total_rows(sheets, client, STAFF, "Expenses", date_column="Date", from_date="June")["error"]
    assert "Unknown column" in total_rows(sheets, client, STAFF, "Expenses", sum_column="Cost")["error"]
    assert "date_column" in total_rows(sheets, client, STAFF, "Expenses", from_date="2026-06-01")["error"]


def test_totals_cap_the_group_list():
    sheets = bakery_sheets()
    sheets.tabs["Expenses"] = [{"Date": "2026-06-01", "Item": "x", "Amount": i, "Category": f"c{i}"} for i in range(35)]
    r = total_rows(sheets, make_client(), STAFF, "Expenses", sum_column="Amount", group_by="Category")
    assert len(r["by"]) == 30 and r["more_groups"] == 5 and next(iter(r["by"])) == "c34"
