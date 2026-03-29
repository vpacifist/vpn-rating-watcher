from playwright.sync_api import sync_playwright

from vpn_rating_watcher.scraper.service import _extract_row, _pick_table_rows

HTML = """
<html>
  <body>
    <table id="ratings">
      <thead><tr><th>VPN</th><th>Checked</th><th>Result</th><th>Price</th></tr></thead>
      <tbody>
        <tr>
          <td><a href="/vpn/one">VPN One</a></td>
          <td>28.03.2026 15:00</td>
          <td>35/36</td>
          <td>$4.99</td>
        </tr>
        <tr>
          <td><a href="/vpn/two">VPN Two</a></td>
          <td>28.03.2026 15:00</td>
          <td>34 / 36</td>
          <td>€5.49</td>
        </tr>
      </tbody>
    </table>
  </body>
</html>
"""


def test_scraper_parses_visible_rows_from_rendered_dom() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content(HTML)

        rows = _pick_table_rows(page)
        parsed = [
            _extract_row(row, idx, "https://vpn.maximkatz.com/")
            for idx, row in enumerate(rows, start=1)
        ]

        browser.close()

    assert len(parsed) == 2
    assert parsed[0].rank_position == 1
    assert parsed[0].vpn_name == "vpn one"
    assert parsed[0].result_raw == "35/36"
    assert parsed[0].score == 35
    assert parsed[0].score_max == 36
    assert parsed[0].price_raw == "$4.99"
    assert str(parsed[0].details_url) == "https://vpn.maximkatz.com/vpn/one"

    assert parsed[1].rank_position == 2
    assert parsed[1].vpn_name == "vpn two"
    assert parsed[1].score == 34
