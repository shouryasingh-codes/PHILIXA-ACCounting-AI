"""Day 1 context regressions. Model output mocked; no paid API calls or Tally writes."""
import json
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services import business_command_service as commands


class ContextTests(unittest.IsolatedAsyncioTestCase):
    async def interpret(self, request, output):
        provider = SimpleNamespace(generate_json=Mock(return_value=json.dumps(output)))
        settings = SimpleNamespace(ai_economy_provider='fake', ai_economy_model='fake',
                                   ai_review_provider='fake', ai_review_model='fake')
        with patch.object(commands, 'get_settings', return_value=settings), \
                patch.object(commands, 'get_ai_provider', return_value=provider):
            parsed = await commands.interpret(request)
        conversation = json.loads(provider.generate_json.call_args.args[1].rsplit('\nConversation: ', 1)[1])
        return parsed, conversation

    async def test_quantity_reply_keeps_purchase_context_and_route(self):
        request = commands.CommandRequest(text='quantity 8 bags', conversation_history=[
            {'role': 'user', 'content': 'Supplier se Cement purchase karna hai'},
            {'role': 'assistant', 'content': 'Quantity, unit aur rate bataiye.'}])
        parsed, conversation = await self.interpret(request, {
            'intent': 'purchase_create', 'item_name': 'Cement', 'party_name': 'Supplier',
            'quantity': '8', 'unit': 'bags'})
        self.assertEqual(conversation['history'], [turn.model_dump() for turn in request.conversation_history])
        self.assertEqual(parsed.intent, 'purchase_create')
        self.assertEqual(parsed.quantity, Decimal('8'))
        self.assertIsNone(parsed.rate)
        self.assertIsNone(parsed.unsupported_reason)

    async def test_item_reply_is_not_a_topic_switch(self):
        request = commands.CommandRequest(text='Cement', conversation_history=[
            {'role': 'user', 'content': 'Supplier se 8 bags 350 per bag kharidna hai'},
            {'role': 'assistant', 'content': 'Kis item ki purchase?'}])
        parsed, conversation = await self.interpret(request, {
            'intent': 'purchase_create', 'item_name': 'Cement', 'party_name': 'Supplier',
            'quantity': '8', 'unit': 'bags', 'rate': '350'})
        self.assertTrue(conversation['history'])
        self.assertEqual(parsed.intent, 'purchase_create')
        self.assertEqual(parsed.rate, Decimal('350'))

    def test_constraints_survive_multiple_detail_turns(self):
        for first in ('GST ke saath Cement purchase karo', 'Cement purchase mat karo',
                      'Cement sale karo', 'Cement return karo'):
            with self.subTest(first=first):
                request = commands.CommandRequest(text='rate 350 per bag', conversation_history=[
                    {'role': 'user', 'content': first},
                    {'role': 'assistant', 'content': 'Quantity?'},
                    {'role': 'user', 'content': 'quantity 8 bags'},
                    {'role': 'assistant', 'content': 'Rate?'}])
                parsed = commands.guard_tally_scope(request, commands.ParsedCommand(intent='purchase_create'))
                self.assertTrue(parsed.unsupported_reason)

    async def test_fresh_stock_queries_send_no_old_purchase_fields(self):
        for text in ('Cement stock kitna hai?', 'Cement ka stock', 'सीमेंट का स्टॉक', 'kitna Cement hai'):
            with self.subTest(text=text):
                request = commands.CommandRequest(text=text, conversation_history=[
                    {'role': 'user', 'content': 'GST purchase from Supplier at 350'}])
                parsed, conversation = await self.interpret(request, {'intent': 'stock_read', 'item_name': 'Cement'})
                self.assertEqual(conversation['history'], [])
                self.assertEqual(parsed.intent, 'stock_read')
                self.assertIsNone(parsed.party_name)
                self.assertIsNone(parsed.rate)

    async def test_fresh_purchase_does_not_inherit_old_gst_or_sale(self):
        request = commands.CommandRequest(text='Rice Supplier se 2 bags 100 per bag purchase karo',
            conversation_history=[{'role': 'user', 'content': 'GST ke saath Cement sale karo'}])
        parsed, conversation = await self.interpret(request, {
            'intent': 'purchase_create', 'item_name': 'Rice', 'party_name': 'Supplier',
            'quantity': '2', 'unit': 'bags', 'rate': '100'})
        self.assertEqual(conversation['history'], [])
        self.assertEqual(parsed.intent, 'purchase_create')
        self.assertIsNone(parsed.unsupported_reason)

    def test_latest_operation_only_is_used_for_later_details(self):
        request = commands.CommandRequest(text='rate 100 per bag', conversation_history=[
            {'role': 'user', 'content': 'GST ke saath Cement sale karo'},
            {'role': 'assistant', 'content': 'Unsupported.'},
            {'role': 'user', 'content': 'Supplier se Rice purchase karna hai'},
            {'role': 'assistant', 'content': 'Quantity?'},
            {'role': 'user', 'content': '2 bags'}])
        parsed = commands.guard_tally_scope(request, commands.ParsedCommand(intent='purchase_create'))
        self.assertEqual(parsed.intent, 'purchase_create')
        self.assertIsNone(parsed.unsupported_reason)
        self.assertEqual(len(commands.command_history(request)), 3)

    def test_read_topic_ends_old_purchase_context(self):
        for query in ('Cement stock kitna hai?', 'Purchase Register', 'Purchase report dikhao'):
            with self.subTest(query=query):
                request = commands.CommandRequest(text='8 bags', conversation_history=[
                    {'role': 'user', 'content': 'Supplier se Cement purchase karna hai'},
                    {'role': 'user', 'content': query},
                    {'role': 'assistant', 'content': 'Read result.'}])
                parsed = commands.guard_tally_scope(request, commands.ParsedCommand(intent='purchase_create'))
                self.assertEqual(parsed.intent, 'inventory_change')

    def test_wrong_adjustment_route_on_purchase_detail_reply_is_repaired(self):
        for intent in ('inventory_change', 'inventory_add'):
            with self.subTest(intent=intent):
                request = commands.CommandRequest(text='quantity 8 bags', conversation_history=[
                    {'role': 'user', 'content': 'Supplier se Cement purchase karna hai'}])
                parsed = commands.guard_tally_scope(request, commands.ParsedCommand(intent=intent, quantity='8', unit='bags'))
                self.assertEqual(parsed.intent, 'purchase_create')

    def test_explicit_adjustments_override_prior_purchase(self):
        cases = [('remove 2 bags Cement', 'inventory_change'),
                 ('Cement actual 8 bags stock correct karo', 'stock_count_set'),
                 ('Cement 8 bags add karo', 'inventory_add')]
        for text, expected in cases:
            with self.subTest(text=text):
                request = commands.CommandRequest(text=text, conversation_history=[
                    {'role': 'user', 'content': 'Cement Supplier se purchase karo'}])
                parsed = commands.guard_tally_scope(request, commands.ParsedCommand(intent='purchase_create'))
                self.assertEqual(parsed.intent, expected)

    def test_physical_count_reply_keeps_count_intent(self):
        request = commands.CommandRequest(text='8 bags', conversation_history=[
            {'role': 'user', 'content': 'Cement ka actual physical count correct karo'}])
        parsed = commands.guard_tally_scope(request, commands.ParsedCommand(intent='stock_count_set', target_quantity='8'))
        self.assertEqual(parsed.intent, 'stock_count_set')

    def test_mutations_ending_in_stock_are_not_reads(self):
        for text in ('remove 2 bags from Cement stock', 'Cement actual 8 bags stock',
                     'delete Cement stock', 'Cement stock kitna remove karo'):
            with self.subTest(text=text):
                self.assertFalse(commands.fresh_stock_question(text))

    def test_bare_confirmation_never_becomes_an_approval(self):
        request = commands.CommandRequest(text='yes confirm', conversation_history=[
            {'role': 'user', 'content': 'Cement Supplier se purchase karo'}])
        parsed = commands.guard_tally_scope(request, commands.ParsedCommand(intent='general'))
        self.assertEqual(parsed.intent, 'general')

    def test_structured_form_does_not_inherit_unrelated_history(self):
        request = commands.CommandRequest(intent='purchase_create', fields={'quantity': '8'},
            conversation_history=[{'role': 'user', 'content': 'GST sale karo'}])
        parsed = commands.guard_tally_scope(request, commands.ParsedCommand(intent=request.intent, **request.fields.model_dump()))
        self.assertEqual(parsed.intent, 'purchase_create')
        self.assertIsNone(parsed.unsupported_reason)


if __name__ == '__main__':
    unittest.main()
