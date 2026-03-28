"""
Playwright-based tests for admin skip link functionality.

This is a migration of test_skip_link_to_content.py from Selenium to
Playwright, demonstrating the API translation and improved testing experience.
"""

from django.contrib.admin.playwright_tests import AdminPlaywrightTestCase
from django.contrib.auth.models import User
from django.test import override_settings
from django.urls import reverse

from .models import Podcast


@override_settings(ROOT_URLCONF="admin_views.urls")
class PlaywrightTests(AdminPlaywrightTestCase):
    available_apps = ["admin_views"] + AdminPlaywrightTestCase.available_apps

    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="super",
            password="secret",
            email="super@example.com",
        )

    def test_use_skip_link_to_content(self):
        self.admin_login(
            username="super",
            password="secret",
            login_url=reverse("admin:index"),
        )

        # `Skip link` is not present (hidden by default).
        skip_link = self.page.locator(".skip-to-content-link")
        self.assertFalse(skip_link.is_visible())

        # 1st TAB is pressed, `skip link` is shown.
        body = self.page.locator("body")
        body.press("Tab")
        self.assertTrue(skip_link.is_visible())

        # Press RETURN to skip the navbar links (view site / documentation /
        # change password / log out) and focus first model in the admin_views
        # list.
        skip_link.press("Enter")
        self.assertFalse(skip_link.is_visible())  # `skip link` disappears.

        # The 1st TAB focuses the section title.
        # For Firefox, it doesn't focus the section title ('ADMIN_VIEWS').
        if self.browser == "firefox":
            self.page.keyboard.press("Tab")
        else:
            self.page.keyboard.press("Tab")
            self.page.keyboard.press("Tab")

        actors_a_tag = self.page.locator("text=Actors").first
        # Check that the Actors link is focused
        focused_element = self.page.evaluate("document.activeElement.textContent")
        self.assertIn("Actors", focused_element)

        # Go to Actors changelist, skip sidebar and focus "Add actor +".
        with self.wait_page_loaded():
            actors_a_tag.press("Enter")

        body = self.page.locator("body")
        body.press("Tab")
        skip_link = self.page.locator(".skip-to-content-link")
        self.assertTrue(skip_link.is_visible())

        self.page.keyboard.press("Enter")
        self.page.keyboard.press("Tab")

        actors_add_url = reverse("admin:admin_views_actor_add")
        actors_a_tag = self.page.locator(f"#content [href='{actors_add_url}']")
        # Verify the add link is focused
        focused_href = self.page.evaluate("document.activeElement.getAttribute('href')")
        self.assertEqual(focused_href, actors_add_url)

        # Go to the Actor form and the first input will be focused
        # automatically.
        with self.wait_page_loaded():
            actors_a_tag.press("Enter")

        # Verify the name input is focused
        focused_id = self.page.evaluate("document.activeElement.id")
        self.assertEqual(focused_id, "id_name")

    def test_dont_use_skip_link_to_content(self):
        self.admin_login(
            username="super",
            password="secret",
            login_url=reverse("admin:index"),
        )

        # `Skip link` is not present (hidden by default).
        skip_link = self.page.locator(".skip-to-content-link")
        self.assertFalse(skip_link.is_visible())

        # 1st TAB is pressed, `skip link` is shown.
        body = self.page.locator("body")
        body.press("Tab")
        self.assertTrue(skip_link.is_visible())

        # The 2nd TAB will focus the page title.
        body.press("Tab")
        self.assertFalse(skip_link.is_visible())  # `skip link` disappears.

        # Check that Django administration link is focused
        focused_text = self.page.evaluate("document.activeElement.textContent")
        self.assertIn("Django administration", focused_text)

    def test_skip_link_with_RTL_language_doesnt_create_horizontal_scrolling(self):
        with override_settings(LANGUAGE_CODE="ar"):
            self.admin_login(
                username="super",
                password="secret",
                login_url=reverse("admin:index"),
            )

            skip_link = self.page.locator(".skip-to-content-link")
            body = self.page.locator("body")
            body.press("Tab")
            self.assertTrue(skip_link.is_visible())

            is_vertical_scrollable = self.page.evaluate(
                "document.body.scrollHeight > document.body.offsetHeight"
            )
            is_horizontal_scrollable = self.page.evaluate(
                "document.body.scrollWidth > document.body.offsetWidth"
            )
            self.assertTrue(is_vertical_scrollable)
            self.assertFalse(is_horizontal_scrollable)

    def test_skip_link_keyboard_navigation_in_changelist(self):
        Podcast.objects.create(name="apple", release_date="2000-09-19")
        self.admin_login(
            username="super",
            password="secret",
            login_url=reverse("admin:index"),
        )
        self.page.goto(
            self.live_server_url + reverse("admin:admin_views_podcast_changelist")
        )

        selectors = [
            "ul.object-tools",  # object_tools.
            "search#changelist-filter",  # list_filter.
            "form#changelist-search",  # search_fields.
            "nav.toplinks",  # date_hierarchy.
            "form#changelist-form div.actions",  # action.
            "table#result_list",  # table.
            "div.changelist-footer",  # footer.
        ]

        content = self.page.locator("#content-start")
        content.press("Tab")

        for selector in selectors:
            with self.subTest(selector=selector):
                # Currently focused element.
                focused_html = self.page.evaluate("document.activeElement.outerHTML")
                expected_element = self.page.locator(selector)
                expected_html = expected_element.evaluate("el => el.innerHTML")

                self.assertIn(focused_html, expected_html)

                # Move to the next container element via TAB.
                # Find the last visible focusable element and tab from there
                focusable = self.page.locator(
                    f"{selector} a, {selector} input, {selector} button"
                ).all()

                for element in reversed(focusable):
                    if element.is_visible():
                        element.press("Tab")
                        break
