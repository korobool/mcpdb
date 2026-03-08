"""Test follow-up suggestion interaction.

Tests: follow-ups render, clicking fires new query, second result appears.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .helpers import (
    connect_database,
    submit_query,
    click_followup,
    get_followup_texts,
    count_messages,
    get_chat_messages,
    take_screenshot,
    wait_for_websocket_connected,
)

DB_URL = "mysql+pymysql://dbtalk:dbtalk@localhost:3306/bgins"


@pytest.fixture
def connected_page(page: Page, web_server):
    page.goto(web_server)
    wait_for_websocket_connected(page)
    page.wait_for_timeout(500)
    connect_database(page, DB_URL)
    page.wait_for_timeout(1000)
    return page


class TestFollowUpSuggestions:
    """Test follow-up buttons."""

    def test_followups_are_buttons(self, connected_page: Page, artifact_dir):
        """Follow-ups should render as clickable buttons."""
        page = connected_page
        result = submit_query(
            page,
            "How many car records are there?",
            mode="simple",
            timeout=120_000,
        )

        assert not result["error"]

        followups = page.locator(".message.assistant:last-child .followup-btn")
        if followups.count() > 0:
            # Should be visible and have text
            first_btn = followups.first
            expect(first_btn).to_be_visible()
            text = first_btn.inner_text()
            assert len(text) > 5, f"Follow-up text too short: {text}"

        take_screenshot(page, "followup_buttons", artifact_dir)

    def test_followup_texts_are_relevant(self, connected_page: Page, artifact_dir):
        """Follow-up suggestions should be relevant questions."""
        page = connected_page
        submit_query(
            page,
            "What are the top 5 car brands by count?",
            mode="simple",
            timeout=120_000,
        )

        texts = get_followup_texts(page)
        # Each follow-up should be a reasonable length question
        for t in texts:
            assert len(t) > 5, f"Follow-up too short: {t}"
            assert len(t) < 200, f"Follow-up too long: {t}"
            # Should end with ? or be a reasonable statement
            assert t[-1] in ("?", ".", "!") or len(t) > 10, f"Odd follow-up: {t}"

    def test_click_followup_fires_query(self, connected_page: Page, artifact_dir):
        """Clicking a follow-up should submit it as a new query."""
        page = connected_page

        # Use a quick-mode question to get fast followups
        result = submit_query(
            page,
            "How many rows in ins_cars?",
            mode="quick",
            timeout=90_000,
        )

        assert not result["error"]
        followups = page.locator(".message.assistant:last-child .followup-btn")
        if followups.count() == 0:
            pytest.skip("No follow-up suggestions generated")

        # Count messages before clicking
        msg_count_before = count_messages(page, "assistant")

        # Get the followup text so we know what's being submitted
        followup_text = followups.first.inner_text()

        # Click the first follow-up
        followups.first.click()

        # Verify the followup text appeared as a user message
        page.wait_for_timeout(1000)
        user_msgs = page.locator(".message.user")
        last_user = user_msgs.last.inner_text() if user_msgs.count() > 0 else ""
        assert followup_text in last_user or user_msgs.count() > 1, \
            "Follow-up click didn't submit a query"

        # Wait for the followup query to complete (generous timeout)
        page.locator("#send-btn").wait_for(state="visible", timeout=180_000)

        # Should have more messages now
        msg_count_after = count_messages(page, "assistant")
        assert msg_count_after > msg_count_before, "No new message after follow-up click"

        take_screenshot(page, "followup_clicked", artifact_dir)
