"""Agent completion alerts via the configured ntfy destination."""
import json
from src.notifications import dispatch_notification

class NotifyUserTool:
    async def execute(self, content, ctx):
        from src.tool_security import owner_is_admin_or_single_user
        owner = ctx.get('owner')
        if not owner or not owner_is_admin_or_single_user(owner):
            return {'error':'Notifications require an administrator account.', 'exit_code':1}
        try:
            args = json.loads(content)
            if not isinstance(args,dict) or set(args)-{'message','title','priority','tags'}:
                raise ValueError()
            result = await dispatch_notification(
                args.get('message',''), title=args.get('title','Exodus'),
                priority=args.get('priority',3), tags=args.get('tags'),
                owner=owner, ai=True, incognito=bool(ctx.get('incognito')))
            return {'output':json.dumps(result), 'exit_code':0 if result['status']=='sent' else 1}
        except (ValueError,TypeError):
            return {'error':'Provide message, optional title, priority (1–5) and tags.', 'exit_code':1}
