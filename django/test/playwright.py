import os
import sys
import unittest
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from django.conf import settings
from django.test import LiveServerTestCase, override_settings, tag
from django.utils.functional import classproperty
from django.utils.text import capfirst

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


class PlaywrightTestCaseBase(type(LiveServerTestCase)):
    """
    Metaclass for PlaywrightTestCase that dynamically creates test classes
    for each browser specified via --playwright=browser1,browser2.
    """

    # List of browsers to dynamically create test classes for.
    browsers = []
    # Sentinel value to differentiate browser-specific instances.
    browser = None
    # Run browsers in headless mode.
    headless = False

    def __new__(cls, name, bases, attrs):
        """
        Dynamically create new classes and add them to the test module when
        multiple browser specs are provided (e.g. --playwright=chromium).
        """
        test_class = super().__new__(cls, name, bases, attrs)
        # If the test class is either browser-specific or a test base, return
        # it.
        if test_class.browser or not any(
            name.startswith("test") and callable(value) for name, value in attrs.items()
        ):
            return test_class
        elif test_class.browsers:
            # Reuse the created test class to make it browser-specific.
            # We can't rename it to include the browser name or create a
            # subclass like we do with the remaining browsers as it would
            # either duplicate tests or prevent pickling of its instances.
            first_browser = test_class.browsers[0]
            test_class.browser = first_browser
            # Create subclasses for each of the remaining browsers and expose
            # them through the test's module namespace.
            module = sys.modules[test_class.__module__]
            for browser in test_class.browsers[1:]:
                browser_test_class = cls.__new__(
                    cls,
                    "%s%s" % (capfirst(browser), name),
                    (test_class,),
                    {
                        "browser": browser,
                        "__module__": test_class.__module__,
                    },
                )
                setattr(module, browser_test_class.__name__, browser_test_class)
            return test_class
        # If no browsers were specified, skip this class (it'll still be
        # discovered).
        return unittest.skip("No browsers specified.")(test_class)


class ChangeWindowSize:
    """Context manager for temporarily changing the browser window size."""

    def __init__(self, width, height, page):
        self.page = page
        self.new_size = {"width": width, "height": height}

    def __enter__(self):
        self.old_size = self.page.viewport_size
        self.page.set_viewport_size(self.new_size)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.old_size:
            self.page.set_viewport_size(self.old_size)


@tag("playwright")
class PlaywrightTestCase(LiveServerTestCase, metaclass=PlaywrightTestCaseBase):
    """
    A test case for browser-based integration tests using Playwright.

    This is the Playwright equivalent of SeleniumTestCase, providing a modern
    testing experience with auto-waiting, cleaner API, and better performance.
    """

    implicit_wait = 10_000  # Playwright uses milliseconds
    screenshots = False

    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not cls.screenshots:
            return

        for name, func in list(cls.__dict__.items()):
            if not hasattr(func, "_screenshot_cases"):
                continue
            # Remove the main test.
            delattr(cls, name)
            # Add separate tests for each screenshot type.
            for screenshot_case in getattr(func, "_screenshot_cases"):

                @wraps(func)
                def test(self, *args, _func=func, _case=screenshot_case, **kwargs):
                    with getattr(self, _case)():
                        return _func(self, *args, **kwargs)

                test.__name__ = f"{name}_{screenshot_case}"
                test.__qualname__ = f"{test.__qualname__}_{screenshot_case}"
                test._screenshot_name = name
                test._screenshot_case = screenshot_case
                setattr(cls, test.__name__, test)

    @classproperty
    def live_server_url(cls):
        return "http://%s:%s" % (cls.host, cls.server_thread.port)

    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:
            raise unittest.SkipTest("Playwright is not installed")

        # sync_playwright starts an internal asyncio event loop that triggers
        # Django's SynchronousOnlyOperation during database access in tests.
        # Setting DJANGO_ALLOW_ASYNC_UNSAFE works around this limitation.
        cls._original_async_unsafe = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

        cls._playwright = sync_playwright().start()
        cls._browser = cls._create_browser()
        cls._context = cls._browser.new_context()
        cls._context.set_default_timeout(cls.implicit_wait)
        cls.page = cls._context.new_page()

        super().setUpClass()
        cls.addClassCleanup(cls._quit_playwright)

    @classmethod
    def _create_browser(cls):
        """Create and return a browser instance based on cls.browser."""
        browser_type = getattr(cls._playwright, cls.browser)
        return browser_type.launch(headless=cls.headless)

    @classmethod
    def _quit_playwright(cls):
        """Clean up Playwright resources."""
        if hasattr(cls, "page") and cls.page:
            cls.page.close()
        if hasattr(cls, "_context") and cls._context:
            cls._context.close()
        if hasattr(cls, "_browser") and cls._browser:
            cls._browser.close()
        if hasattr(cls, "_playwright") and cls._playwright:
            cls._playwright.stop()

        # Restore the original DJANGO_ALLOW_ASYNC_UNSAFE value.
        if cls._original_async_unsafe is None:
            os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)
        else:
            os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = cls._original_async_unsafe

    @contextmanager
    def desktop_size(self):
        """Set the viewport to desktop size (1280x720)."""
        with ChangeWindowSize(1280, 720, self.page):
            yield

    @contextmanager
    def small_screen_size(self):
        """Set the viewport to small screen size (1024x768)."""
        with ChangeWindowSize(1024, 768, self.page):
            yield

    @contextmanager
    def mobile_size(self):
        """Set the viewport to mobile size (360x800)."""
        with ChangeWindowSize(360, 800, self.page):
            yield

    @contextmanager
    def rtl(self):
        """Set the language to a right-to-left language."""
        with self.desktop_size():
            with override_settings(LANGUAGE_CODE=settings.LANGUAGES_BIDI[-1]):
                yield

    @contextmanager
    def dark(self):
        """Enable dark mode theme."""
        # Navigate to a page before executing a script.
        self.page.goto(self.live_server_url)
        self.page.evaluate("localStorage.setItem('theme', 'dark');")
        with self.desktop_size():
            try:
                yield
            finally:
                self.page.evaluate("localStorage.removeItem('theme');")

    @contextmanager
    def high_contrast(self):
        """Enable high contrast mode (Chromium only)."""
        if self.browser != "chromium":
            self.skipTest("Emulation.setEmulatedMedia is only supported on Chromium.")
        self.page.emulate_media(forced_colors="active")
        with self.desktop_size():
            try:
                yield
            finally:
                self.page.emulate_media(forced_colors="none")

    @contextmanager
    def disable_implicit_wait(self):
        """Disable the default implicit wait."""
        self.page.set_default_timeout(0)
        try:
            yield
        finally:
            self.page.set_default_timeout(self.implicit_wait)

    def take_screenshot(self, name):
        """Take a screenshot if screenshots are enabled."""
        if not self.screenshots:
            return
        test = getattr(self, self._testMethodName)
        filename = f"{test._screenshot_name}--{name}--{test._screenshot_case}.png"
        path = Path.cwd() / "screenshots" / filename
        path.parent.mkdir(exist_ok=True, parents=True)
        self.page.screenshot(path=str(path))

    def assertNoAccessibilityViolations(self, context=None, options=None):
        """
        Assert that the current page has no accessibility violations.

        Uses axe-playwright-python to run axe-core accessibility checks.
        Skips the test if axe-playwright-python is not installed.

        Args:
            context: Optional axe-core context (selector or element reference)
            options: Optional axe-core options (rules to run, etc.)

        See https://github.com/dequelabs/axe-core/blob/develop/doc/API.md
        for context and options documentation.
        """
        try:
            from axe_playwright_python.sync_playwright import Axe
        except ImportError:
            self.skipTest("axe-playwright-python is not installed")

        results = Axe().run(self.page, context, options)
        self.assertEqual(
            results.violations_count,
            0,
            "Accessibility violations found:\n%s" % results.generate_report(),
        )


def screenshot_cases(method_names):
    """
    Decorator to run a test method for multiple screenshot cases.

    Usage:
        @screenshot_cases("desktop_size,mobile_size,dark")
        def test_my_feature(self):
            ...
    """
    if isinstance(method_names, str):
        method_names = method_names.split(",")

    def wrapper(func):
        func._screenshot_cases = method_names
        setattr(func, "tags", {"screenshot"}.union(getattr(func, "tags", set())))
        return func

    return wrapper
