"""Request checks kept independent of the web framework for offline testing."""
import secrets


def check_request(host,origin,site,path,provided,expected,testing=False):
    hosts={'127.0.0.1:8765','localhost:8765'}
    if testing:hosts.add('testserver')
    if host not in hosts:return 403,'Use http://127.0.0.1:8765'
    local={'http://127.0.0.1:8765','http://localhost:8765'}
    if origin and origin not in local and not origin.startswith('chrome-extension://'):
        return 403,'Origin is not allowed'
    if path.startswith('/api/'):
        paired=bool(expected) and secrets.compare_digest(provided,expected)
        if path=='/api/session':
            if ((origin and origin not in local) or site=='cross-site') and not paired:
                return 403,'Open local settings or use your setup token to pair Unscroll'
        elif not paired:return 401,'Pair with Unscroll using its local token'
    return None
