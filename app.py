from flask import Flask, render_template, request, jsonify, session
import json
from powerbi_api_connector import PowerBIAPIConnector, create_auto_connector
import os
from datetime import datetime
from cache import cache_result
from security import token_required, rate_limit, validate_powerbi_credentials, sanitize_input, log_security_event

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(32))

# ตัวแปร global สำหรับเก็บ connector
pbi_connector = None

@app.route('/')
def index():
    """หน้าแรก"""
    return render_template('index.html')

@app.route('/connect', methods=['POST'])
@rate_limit(max_requests=10, window=60)
def connect():
    """เชื่อมต่อกับ Power BI"""
    global pbi_connector
    
    try:
        data = request.get_json()
        
        # Validate input
        if not data:
            return jsonify({
                'success': False,
                'message': 'Invalid request data'
            })
        
        # ตรวจสอบว่าต้องการ auto-detect หรือไม่
        if data.get('auto_detect', False):
            # แบบ auto-detect จาก environment
            pbi_connector = create_auto_connector()
            connection_type = "Auto-detect"
        else:
            # แบบ manual - validate credentials
            tenant_id = sanitize_input(data.get('tenant_id', ''))
            client_id = sanitize_input(data.get('client_id', ''))
            client_secret = sanitize_input(data.get('client_secret', ''))
            
            is_valid, message = validate_powerbi_credentials({
                'tenant_id': tenant_id,
                'client_id': client_id,
                'client_secret': client_secret
            })
            
            if not is_valid:
                log_security_event('INVALID_CREDENTIALS', 'anonymous', message)
                return jsonify({
                    'success': False,
                    'message': message
                })
            
            pbi_connector = PowerBIAPIConnector(tenant_id, client_id, client_secret, auto_detect=False)
            connection_type = "Manual"
        
        # ทดสอบการเชื่อมต่อโดยดึง workspaces
        workspaces = pbi_connector.get_workspaces()
        
        session['connected'] = True
        session['connection_type'] = connection_type
        
        log_security_event('CONNECTION_SUCCESS', session.get('user_id', 'anonymous'), connection_type)
        
        return jsonify({
            'success': True,
            'message': f'เชื่อมต่อสำเร็จ ({connection_type})',
            'workspaces_count': len(workspaces),
            'connection_type': connection_type
        })
        
    except Exception as e:
        log_security_event('CONNECTION_ERROR', session.get('user_id', 'anonymous'), str(e))
        return jsonify({
            'success': False,
            'message': f'เชื่อมต่อล้มเหลว: {sanitize_input(str(e))}'
        })

@app.route('/connect-auto', methods=['POST'])
def connect_auto():
    """เชื่อมต่อแบบอัตโนมัติจาก environment"""
    global pbi_connector
    
    try:
        pbi_connector = create_auto_connector()
        
        # ทดสอบการเชื่อมต่อ
        workspaces = pbi_connector.get_workspaces()
        
        session['connected'] = True
        session['connection_type'] = 'Auto-detect'
        
        return jsonify({
            'success': True,
            'message': 'เชื่อมต่ออัตโนมัติสำเร็จ',
            'workspaces_count': len(workspaces),
            'connection_type': 'Auto-detect'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'เชื่อมต่ออัตโนมัติล้มเหลว: {str(e)}'
        })

@app.route('/workspaces')
@token_required
@rate_limit(max_requests=50, window=300)
@cache_result(expiration=300)
def get_workspaces():
    """ดึงรายการ Workspaces"""
    global pbi_connector
    
    if not pbi_connector:
        return jsonify({'success': False, 'message': 'กรุณาเชื่อมต่อก่อน'})
    
    try:
        workspaces = pbi_connector.get_workspaces()
        return jsonify({
            'success': True,
            'workspaces': workspaces
        })
    except Exception as e:
        log_security_event('WORKSPACE_ERROR', session.get('user_id', 'anonymous'), str(e))
        return jsonify({
            'success': False,
            'message': sanitize_input(str(e))
        })

@app.route('/workspace/<workspace_id>/datasets')
def get_datasets(workspace_id):
    """ดึงรายการ Datasets ใน Workspace"""
    global pbi_connector
    
    if not pbi_connector:
        return jsonify({'success': False, 'message': 'กรุณาเชื่อมต่อก่อน'})
    
    try:
        datasets = pbi_connector.get_datasets(workspace_id)
        return jsonify({
            'success': True,
            'datasets': datasets
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.route('/workspace/<workspace_id>/reports')
def get_reports(workspace_id):
    """ดึงรายการ Reports ใน Workspace"""
    global pbi_connector
    
    if not pbi_connector:
        return jsonify({'success': False, 'message': 'กรุณาเชื่อมต่อก่อน'})
    
    try:
        reports = pbi_connector.get_reports(workspace_id)
        return jsonify({
            'success': True,
            'reports': reports
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.route('/query', methods=['POST'])
def execute_query():
    """รันคำสั่ง DAX"""
    global pbi_connector
    
    if not pbi_connector:
        return jsonify({'success': False, 'message': 'กรุณาเชื่อมต่อก่อน'})
    
    try:
        data = request.get_json()
        workspace_id = data.get('workspace_id')
        dataset_id = data.get('dataset_id')
        dax_query = data.get('dax_query')
        
        if not all([workspace_id, dataset_id, dax_query]):
            return jsonify({
                'success': False,
                'message': 'กรุณากรอกข้อมูลให้ครบถ้วน'
            })
        
        result = pbi_connector.execute_dax_query(workspace_id, dataset_id, dax_query)
        
        return jsonify({
            'success': True,
            'result': result
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.route('/refresh', methods=['POST'])
def refresh_dataset():
    """รีเฟรช Dataset"""
    global pbi_connector
    
    if not pbi_connector:
        return jsonify({'success': False, 'message': 'กรุณาเชื่อมต่อก่อน'})
    
    try:
        data = request.get_json()
        workspace_id = data.get('workspace_id')
        dataset_id = data.get('dataset_id')
        
        if not all([workspace_id, dataset_id]):
            return jsonify({
                'success': False,
                'message': 'กรุณาระบุ workspace_id และ dataset_id'
            })
        
        result = pbi_connector.refresh_dataset(workspace_id, dataset_id)
        
        return jsonify({
            'success': True,
            'result': result
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port, use_reloader=False)
