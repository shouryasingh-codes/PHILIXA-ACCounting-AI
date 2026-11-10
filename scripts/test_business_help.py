import unittest
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from app.services.business_help import help_answer
from app.api.v1.routes_business import command
from app.services.business_command_service import CommandRequest


class HelpTests(unittest.IsolatedAsyncioTestCase):
    def test_help_variants(self):
        for message in ('hyy tu maire liye kiya kr sakta hai', 'Hello, what can you do for me?', 'Hey! how can you help me?', 'whatyou can do for me', 'What can you do?',
                        'how can you help me?', 'tum kya kar sakte ho',
                        'tu maire liye kiya kr sakta hai',
                        'Bhai, tu mere liye kya kya kar sakta hai?',
                        'aap mere liye kya kar sakte hain',
                        'tum kya mere liye kar sakte ho',
                        'tu meri help kaise kr sakta hai',
                        'आप क्या कर सकते हैं'):
            self.assertIsNotNone(help_answer(message), message)

    def test_greetings_compose_with_help_but_not_mixed_commands(self):
        for greeting in ('Hi, ', 'Hey! ', 'Hello ', 'hyy ', 'Namaste, ', 'Bhai, '):
            for body in ('what can you do for me?', 'tu maire liye kiya kr sakta hai'):
                self.assertIsNotNone(help_answer(greeting + body))
                self.assertIsNone(help_answer(greeting + body + ' aur 5 bags add kar'))

    def test_business_requests_do_not_get_swallowed(self):
        for message in ('what can you do for me and add 5 bags', 'stock kitna hai',
                        'Sharma Traders', 'what can you do for my invoice?',
                        'purchase entry karo', 'help me delete stock'):
            self.assertIsNone(help_answer(message), message)

    def test_mixed_hinglish_commands_stay_out_of_static_help(self):
        for message in ('tu maire liye kiya kr sakta hai aur 5 bags add kar',
                        'tum mere liye kya purchase kar sakte ho',
                        'tu mere liye kya stock check kar sakta hai',
                        'tu meri help kar Sharma ko payment karo'):
            self.assertIsNone(help_answer(message), message)

    async def test_existing_task_is_not_resumed_for_help(self):
        with patch.dict(os.environ,{'PHILIXA_INTENT_ROUTER_ENABLED':'0','PHILIXA_TASK_AGENT_ENABLED':'0'}), \
             patch('app.services.task_agent_service.resume',new_callable=AsyncMock) as resume, \
             patch('app.services.task_agent_service.create',new_callable=AsyncMock) as create:
            for message in ('hyy tu maire liye kiya kr sakta hai','Hello, what can you do for me?','whatyou can do for me','tu maire liye kiya kr sakta hai'):
                result=await command(CommandRequest(text=message,
                    task_id='a'*32,request_id='help-request-123456',expected_revision=0),
                    SimpleNamespace(),AsyncMock())
                self.assertEqual(result['status'],'completed')
                self.assertNotIn('task_id',result)
            resume.assert_not_awaited();create.assert_not_awaited()


if __name__=='__main__':unittest.main()
