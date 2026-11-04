"""Configure secrets on the owner's Mac, never in a chat or browser form."""
import getpass
import os
from pathlib import Path
from dotenv import dotenv_values

path=Path(__file__).parent/'.env'
current=dict(dotenv_values(path)) if path.exists() else {}
print('\nUnscroll keeps media and extraction on this Mac. Extracted text is sent to Claude.')
print('A paid Claude API key is separate from a Claude chat subscription.')
key=getpass.getpass('Claude API key (hidden; Enter keeps the existing key or skips): ').strip()
if key: current['ANTHROPIC_API_KEY']=key
default=current.get('UNSCROLL_CLAUDE_MODEL') or 'claude-haiku-5-5'
model=input(f'Claude model ID [{default}]: ').strip() or default
current['UNSCROLL_CLAUDE_MODEL']=model
current['UNSCROLL_WHISPER_MODEL']=current.get('UNSCROLL_WHISPER_MODEL') or 'base.en'
def quote(value):
    return "'"+str(value).replace('\\','\\\\').replace("'","\\'").replace('\n','')+"'"
fd=os.open(path,os.O_CREAT|os.O_WRONLY|os.O_TRUNC,0o600)
os.chmod(path,0o600)
with os.fdopen(fd,'w') as f:
    f.write('\n'.join(k+'='+quote(v) for k,v in current.items() if v is not None)+'\n')
print('Local configuration saved. You can rerun Setup.command to change it.')
