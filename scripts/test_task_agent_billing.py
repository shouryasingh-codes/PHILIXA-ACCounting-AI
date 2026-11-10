"""Billing mode is configured explicitly, never guessed from API key or model."""
import unittest
from decimal import Decimal
from unittest.mock import patch
from app.jobs.task_agent_jobs import billing_limits


class BillingTests(unittest.TestCase):
    def test_unset_budget_stops_paid_calls(self):
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(ValueError):billing_limits()

    def test_free_mode_requires_account_confirmation(self):
        with patch.dict('os.environ',{'PHILIXA_TASK_AGENT_BILLING_MODE':'free'},clear=True):
            with self.assertRaises(ValueError):billing_limits()

    def test_confirmed_free_mode_reserves_no_dollars(self):
        with patch.dict('os.environ',{'PHILIXA_TASK_AGENT_BILLING_MODE':'free',
            'PHILIXA_GROQ_FREE_TIER_CONFIRMED':'1'},clear=True):
            self.assertEqual(billing_limits(),('free',Decimal(0),Decimal(0)))

    def test_nan_and_negative_paid_caps_rejected(self):
        for cap in ('NaN','Infinity','-1','0'):
            with self.subTest(cap=cap),patch.dict('os.environ',{'PHILIXA_TASK_AGENT_DAILY_USD':cap},clear=True):
                with self.assertRaises(ValueError):billing_limits()

    def test_unknown_mode_does_not_fall_back_to_paid(self):
        with patch.dict('os.environ',{'PHILIXA_TASK_AGENT_BILLING_MODE':'anything'},clear=True):
            with self.assertRaises(ValueError):billing_limits()


if __name__=='__main__':unittest.main()
