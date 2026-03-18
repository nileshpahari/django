from contextlib import contextmanager

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import modify_settings, override_settings
from django.test.playwright import PlaywrightTestCase
from django.utils.csp import CSP
from django.utils.translation import gettext as _

# Make unittest ignore frames in this module when reporting failures.
__unittest = True


@modify_settings(
    MIDDLEWARE={"append": "django.middleware.csp.ContentSecurityPolicyMiddleware"}
)
@override_settings(
    SECURE_CSP={
        "default-src": [CSP.NONE],
        "connect-src": [CSP.SELF],
        "img-src": [CSP.SELF],
        "script-src": [CSP.SELF],
        "style-src": [CSP.SELF],
    },
)
class AdminPlaywrightTestCase(PlaywrightTestCase, StaticLiveServerTestCase):
    """
    A test case for admin browser-based integration tests using Playwright.

    This is the Playwright equivalent of AdminSeleniumTestCase, providing
    admin-specific helper methods for login, form interaction, and waiting.
    """

    available_apps = [
        "django.contrib.admin",
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "django.contrib.sites",
    ]

    def wait_until(self, js_expression, timeout=10):
        """
        Block the execution of the tests until the specified JavaScript
        expression returns a value that is not falsy. This method can be
        called, for example, after clicking a link or submitting a form.

        Unlike AdminSeleniumTestCase.wait_until() which accepts a Python
        callable, this method requires a JavaScript expression string because
        Playwright evaluates expressions in the browser context.

        Note: Playwright has built-in auto-waiting, so this method is often
        unnecessary. Prefer using locator.wait_for() or expect() assertions.

        Example:
            self.wait_until("document.querySelector('.loaded') !== null")
        """
        timeout_ms = timeout * 1000
        self.page.wait_for_function(js_expression, timeout=timeout_ms)

    def wait_for(self, css_selector, timeout=10):
        """
        Block until a CSS selector is found on the page.
        """
        timeout_ms = timeout * 1000
        self.page.wait_for_selector(css_selector, timeout=timeout_ms)

    def wait_for_text(self, css_selector, text, timeout=10):
        """
        Block until the text is found in the CSS selector.
        """
        timeout_ms = timeout * 1000
        locator = self.page.locator(css_selector)
        locator.wait_for(state="visible", timeout=timeout_ms)
        # Use Playwright's built-in text assertion
        self.page.wait_for_function(
            f"document.querySelector('{css_selector}').textContent.includes('{text}')",
            timeout=timeout_ms,
        )

    def wait_for_value(self, css_selector, text, timeout=10):
        """
        Block until the value is found in the CSS selector.
        """
        timeout_ms = timeout * 1000
        locator = self.page.locator(css_selector)
        locator.wait_for(state="visible", timeout=timeout_ms)
        # Use Playwright's built-in value check
        self.page.wait_for_function(
            f"document.querySelector('{css_selector}').value.includes('{text}')",
            timeout=timeout_ms,
        )

    def wait_until_visible(self, css_selector, timeout=10):
        """
        Block until the element described by the CSS selector is visible.
        """
        timeout_ms = timeout * 1000
        self.page.wait_for_selector(css_selector, state="visible", timeout=timeout_ms)

    def wait_until_invisible(self, css_selector, timeout=10):
        """
        Block until the element described by the CSS selector is invisible.
        """
        timeout_ms = timeout * 1000
        self.page.wait_for_selector(css_selector, state="hidden", timeout=timeout_ms)

    def wait_page_ready(self, timeout=10):
        """
        Block until the page is ready.
        """
        timeout_ms = timeout * 1000
        self.page.wait_for_function(
            "document.readyState === 'complete'",
            timeout=timeout_ms,
        )

    @contextmanager
    def wait_page_loaded(self, timeout=10):
        """
        Block until a new page has loaded and is ready.
        """
        timeout_ms = timeout * 1000

        # Get a reference to current page state
        old_url = self.page.url

        yield

        # Wait for navigation to complete
        try:
            self.page.wait_for_url(
                lambda url: url != old_url,
                timeout=timeout_ms,
            )
        except Exception:
            # URL might be the same but page reloaded
            pass

        self.wait_page_ready(timeout=timeout)

    def trigger_resize(self):
        """Trigger a window resize event."""
        size = self.page.viewport_size
        self.page.set_viewport_size(
            {"width": size["width"] + 1, "height": size["height"]}
        )
        self.wait_page_ready()
        self.page.set_viewport_size(size)
        self.wait_page_ready()

    def admin_login(self, username, password, login_url="/admin/"):
        """
        Log in to the admin.
        """
        self.page.goto("%s%s" % (self.live_server_url, login_url))
        self.page.fill('input[name="username"]', username)
        self.page.fill('input[name="password"]', password)
        login_text = _("Log in")
        with self.wait_page_loaded():
            self.page.click(f'input[value="{login_text}"]')

    def select_option(self, selector, value):
        """
        Select the <OPTION> with the value `value` inside the <SELECT> widget
        identified by the CSS selector `selector`.
        """
        self.page.select_option(selector, value)

    def deselect_option(self, selector, value):
        """
        Deselect the <OPTION> with the value `value` inside the <SELECT> widget
        identified by the CSS selector `selector`.
        """
        # Playwright doesn't have a direct deselect, we need to use evaluate
        self.page.evaluate(
            """([selector, value]) => {
                const select = document.querySelector(selector);
                const option = select.querySelector(`option[value="${value}"]`);
                if (option) option.selected = false;
            }""",
            [selector, value],
        )

    def assertCountPlaywrightElements(self, selector, count, root_element=None):
        """
        Assert number of matches for a CSS selector.
        """
        if root_element:
            locator = root_element.locator(selector)
        else:
            locator = self.page.locator(selector)
        actual_count = locator.count()
        self.assertEqual(actual_count, count)

    def _assertOptionsValues(self, options_selector, values):
        if values:
            options = self.page.locator(options_selector).all()
            actual_values = []
            for option in options:
                actual_values.append(option.get_attribute("value"))
            self.assertEqual(values, actual_values)
        else:
            # Check that no options exist
            with self.disable_implicit_wait():
                count = self.page.locator(options_selector).count()
                self.assertEqual(count, 0)

    def assertSelectOptions(self, selector, values):
        """
        Assert that the <SELECT> widget identified by `selector` has the
        options with the given `values`.
        """
        self._assertOptionsValues("%s > option" % selector, values)

    def assertSelectedOptions(self, selector, values):
        """
        Assert that the <SELECT> widget identified by `selector` has the
        selected options with the given `values`.
        """
        self._assertOptionsValues("%s > option:checked" % selector, values)

    def is_disabled(self, selector):
        """
        Return True if the element identified by `selector` has the `disabled`
        attribute.
        """
        return self.page.locator(selector).is_disabled()
