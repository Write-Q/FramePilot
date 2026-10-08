"""可配置生图网关和单进程图片作业；重启后显式重试。"""
import base64
import json
import os
from pathlib import Path
from uuid import uuid4
import httpx
from app.game.service import GameConflict


class HttpImageProvider:
    """网关契约：JSON输入参考图片base64，JSON输出图片base64。"""
    def __init__(self):
        self.url=os.getenv('GAME_IMAGE_API_URL','');self.key=os.getenv('GAME_IMAGE_API_KEY','')
        self.model=os.getenv('GAME_IMAGE_MODEL','')
        self.configured=bool(self.url)

    def generate(self,prompt,references):
        if not self.configured: raise GameConflict('生图接口未配置。')
        headers={'Authorization':'Bearer '+self.key} if self.key else {}
        payload={'model':self.model,'prompt':prompt,'width':1024,'height':768,
                 'references':[{'mime_type':r['mime_type'],'image_base64':base64.b64encode(r['data']).decode()} for r in references]}
        # 不自动重试付费请求，不接受远程图片URL，避免下载任意地址。
        with httpx.Client(timeout=180,follow_redirects=False) as client:
            with client.stream('POST',self.url,json=payload,headers=headers) as response:
                response.raise_for_status(); chunks=[];size=0
                for chunk in response.iter_bytes():
                    size+=len(chunk)
                    if size>18*1024*1024: raise ValueError('生图响应过大')
                    chunks.append(chunk)
                import json
                result=json.loads(b''.join(chunks))
        data=base64.b64decode(result['image_base64'],validate=True);mime=result['mime_type']
        valid=(mime=='image/png' and data.startswith(b'\x89PNG\r\n\x1a\n')) or (mime=='image/jpeg' and data.startswith(b'\xff\xd8\xff')) or (mime=='image/webp' and data.startswith(b'RIFF') and data[8:12]==b'WEBP')
        if not valid or len(data)>12*1024*1024: raise ValueError('生图响应格式无效')
        return data,mime


class GameImages:
    """图片状态与原回合绑定，任务结束不受当前分支切换影响。"""
    def __init__(self,game,provider,root):
        self.game=game;self.provider=provider;self.root=Path(root).resolve()
        self.root.mkdir(parents=True,exist_ok=True)

    def reserve(self,identifier,turn_id):
        with self.game.operation_lock(identifier):
            s=self.game.get(identifier)
            if not self.provider.configured: raise GameConflict('生图接口未配置，文字游戏可继续。')
            if s['image_calls']>=20: raise GameConflict('本局已达到20次图片请求上限。')
            if not s['turns']: raise GameConflict('请先完成开局。')
            allowed=self.game.lineage(s,self.game.current(s)['id'])
            turn=next((t for t in allowed if t['id']==turn_id),None)
            if not turn: raise GameConflict('该回合不在当前路线中。')
            if any(i['turn_id']==turn_id and i['status'] in ('pending','running') for i in s['images']):
                raise GameConflict('该回合正在生图，请等待。')
            refs=self.game.references(s,turn_id)
            job={'id':uuid4().hex,'turn_id':turn_id,'status':'pending','references':[i['id'] for i in refs],
                 'prompt':'保持参考图中的同名人物外貌与画风；只表现当前可见剧情。场景：'+turn['state']['scene']+'。人物：'+'、'.join(turn['state']['characters'])+'。当前已知设定：'+json.dumps(turn['state'].get('facts',[]),ensure_ascii=False)+'。画面：'+turn['text'],
                 'characters':turn['state']['characters'],'scene':turn['state']['scene'],'model':getattr(self.provider,'model','custom'),
                 'error':None,'file':None,'mime_type':None}
            s['image_calls']+=1;s['images'].append(job);self.game.save(s)
            return job['id']

    def run(self,identifier,job_id):
        with self.game.operation_lock(identifier):
            s=self.game.get(identifier);job=next(i for i in s['images'] if i['id']==job_id)
            if job['status']!='pending':return
            job['status']='running';self.game.save(s)
            refs=[i for i in s['images'] if i['id'] in job['references']]
        try:
            inputs=[{'data':self.path(identifier,i['file']).read_bytes(),'mime_type':i['mime_type']} for i in refs]
            data,mime=self.provider.generate(job['prompt'],inputs)
            suffix={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp'}[mime]
            name=job_id+suffix; target=self.path(identifier,name);target.parent.mkdir(parents=True,exist_ok=True)
            temporary=target.with_suffix('.tmp');temporary.write_bytes(data);temporary.replace(target)
            update={'status':'ready','file':name,'mime_type':mime,'size_bytes':len(data)}
        except Exception:
            update={'status':'failed','error':'图片未生成。请检查接口配置后手动重试；本次请求仍计入额度。'}
        with self.game.operation_lock(identifier):
            s=self.game.get(identifier);next(i for i in s['images'] if i['id']==job_id).update(update);self.game.save(s)

    def path(self,identifier,name):
        """仅允许本库生成的存档编号和媒体文件名。"""
        if not identifier.isalnum() or not name or Path(name).name!=name: raise GameConflict('无效图片地址。')
        target=(self.root/identifier/name).resolve()
        if not target.is_relative_to(self.root): raise GameConflict('无效图片地址。')
        return target

    def recover(self):
        """后台线程不是可靠队列；重启记录中断，避免偷偷重复计费。"""
        for s in self.game.store.list():
            changed=False
            for image in s['images']:
                if image['status'] in ('pending','running'):
                    image.update(status='failed',error='应用重启使图片任务中断，请手动重试。');changed=True
            if changed:self.game.save(s)
