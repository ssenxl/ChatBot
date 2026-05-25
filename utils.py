import re

def extract_info(message, keywords):
    """แยกข้อมูลจากข้อความตามคำสำคัญ"""
    message_lower = message.lower()
    
    for keyword in keywords:
        # หา pattern ต่างๆ
        patterns = [
            rf'{keyword}[:\s]*([a-f0-9-]+)',  # tenant_id: xxxxx
            rf'{keyword}[:\s]*([a-f0-9-]+)',  # client_id: xxxxx
            rf'{keyword}[:\s]*([^\s]+)',     # อื่นๆ
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message_lower)
            if match:
                return match.group(1).strip()
    
    return None

def auto_connect_from_message(message):
    """พยายามแยกข้อมูลเชื่อมต่อจากข้อความและเชื่อมต่ออัตโนมัติ"""
    tenant_id = extract_info(message, ['tenant id', 'tenant', 'directory id'])
    client_id = extract_info(message, ['client id', 'client', 'application id'])
    client_secret = extract_info(message, ['client secret', 'secret', 'key'])
    
    if tenant_id and client_id and client_secret:
        return {
            'tenant_id': tenant_id,
            'client_id': client_id,
            'client_secret': client_secret
        }
    
    return None
