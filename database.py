import os
import json
import psycopg2
import psycopg2.extras
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash


class Database:
    def __init__(self, db_path=None):  # db_path ไม่ใช้แล้ว คงไว้เพื่อ compat
        self._dsn = os.environ['DATABASE_URL']
        self.init_database()

    def get_connection(self):
        return psycopg2.connect(self._dsn, cursor_factory=psycopg2.extras.RealDictCursor)

    def init_database(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id),
                sender TEXT NOT NULL,
                message TEXT NOT NULL,
                message_type TEXT DEFAULT 'text',
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS powerbi_connections (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                tenant_id TEXT,
                client_id TEXT,
                connection_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS activity_logs (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                action TEXT NOT NULL,
                details TEXT,
                ip_address TEXT,
                user_agent TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS intent_logs (
                id SERIAL PRIMARY KEY,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id),
                message_id INTEGER REFERENCES messages(id),
                user_message TEXT NOT NULL,
                detected_intent TEXT NOT NULL,
                confidence REAL NOT NULL,
                matched_keywords TEXT,
                processing_path TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mcp_interactions (
                id SERIAL PRIMARY KEY,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id),
                message_id INTEGER REFERENCES messages(id),
                intent_log_id INTEGER REFERENCES intent_logs(id),
                mcp_server TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                tool_arguments TEXT,
                tool_result TEXT,
                success BOOLEAN DEFAULT TRUE,
                error_message TEXT,
                execution_time_ms INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS suggestions (
                id SERIAL PRIMARY KEY,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id),
                message_id INTEGER REFERENCES messages(id),
                suggestion_text TEXT NOT NULL,
                suggestion_intent TEXT,
                priority INTEGER DEFAULT 3,
                was_clicked BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                clicked_at TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS token_usage (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                conversation_id INTEGER REFERENCES conversations(id),
                message_id INTEGER REFERENCES messages(id),
                model TEXT,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                total_tokens INTEGER,
                tool_calls_count INTEGER DEFAULT 0,
                response_time_ms INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute("SELECT COUNT(*) AS cnt FROM users")
        if cursor.fetchone()['cnt'] == 0:
            cursor.execute(
                "INSERT INTO users (username, email, password_hash, role) VALUES (%s, %s, %s, %s)",
                ('admin', 'admin@powerbi.com', generate_password_hash('adminscm'), 'admin')
            )
            cursor.execute(
                "INSERT INTO users (username, email, password_hash, role) VALUES (%s, %s, %s, %s)",
                ('user', 'user@powerbi.com', generate_password_hash('user123'), 'user')
            )

        conn.commit()
        conn.close()

    # User Management
    def create_user(self, username, email, password, role='user'):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO users (username, email, password_hash, role) VALUES (%s, %s, %s, %s) RETURNING id",
                (username, email, generate_password_hash(password), role)
            )
            user_id = cursor.fetchone()['id']
            conn.commit()
            return user_id
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            return None
        finally:
            conn.close()

    def authenticate_user(self, username, password):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, email, password_hash, role, is_active FROM users WHERE username = %s",
            (username,)
        )
        user = cursor.fetchone()
        conn.close()
        if user and user['is_active'] and check_password_hash(user['password_hash'], password):
            return {'id': user['id'], 'username': user['username'], 'email': user['email'], 'role': user['role']}
        return None

    def update_last_login(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = %s", (user_id,))
        conn.commit()
        conn.close()

    def change_password(self, user_id, old_password, new_password):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash FROM users WHERE id = %s AND is_active = TRUE", (user_id,))
        row = cursor.fetchone()
        if not row or not check_password_hash(row['password_hash'], old_password):
            conn.close()
            return False
        cursor.execute("UPDATE users SET password_hash = %s WHERE id = %s",
                       (generate_password_hash(new_password), user_id))
        conn.commit()
        conn.close()
        return True

    def get_all_users(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, email, role, is_active, created_at, last_login FROM users ORDER BY id")
        users = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return users

    def toggle_user_active(self, user_id, is_active):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET is_active = %s WHERE id = %s AND role != 'admin'",
            (is_active, user_id)
        )
        updated = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return updated

    def admin_reset_password(self, user_id, new_password):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password_hash = %s WHERE id = %s",
                       (generate_password_hash(new_password), user_id))
        updated = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return updated

    def get_user_by_username(self, username):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, email, role FROM users WHERE username = %s AND is_active = TRUE",
            (username,)
        )
        user = cursor.fetchone()
        conn.close()
        return dict(user) if user else None

    def get_user_by_identifier(self, identifier):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, email, role FROM users WHERE (username = %s OR email = %s) AND is_active = TRUE",
            (identifier, identifier)
        )
        user = cursor.fetchone()
        conn.close()
        return dict(user) if user else None

    def update_user_password(self, user_id, new_password):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password_hash = %s WHERE id = %s",
                       (generate_password_hash(new_password), user_id))
        updated = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return updated

    def reset_password_by_identifier(self, identifier, new_password='password123'):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, email FROM users WHERE (username = %s OR email = %s) AND is_active = TRUE",
            (identifier, identifier)
        )
        user = cursor.fetchone()
        if not user:
            conn.close()
            return None
        cursor.execute("UPDATE users SET password_hash = %s WHERE id = %s",
                       (generate_password_hash(new_password), user['id']))
        conn.commit()
        conn.close()
        return dict(user)

    # Conversation Management
    def create_conversation(self, user_id, title=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO conversations (user_id, title) VALUES (%s, %s) RETURNING id",
            (user_id, title or f"Conversation {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        )
        conversation_id = cursor.fetchone()['id']
        conn.commit()
        conn.close()
        return conversation_id

    def get_conversation(self, conversation_id, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE id = %s AND user_id = %s AND is_active = TRUE",
            (conversation_id, user_id)
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def add_message(self, conversation_id, sender, message, message_type='text', metadata=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO messages (conversation_id, sender, message, message_type, metadata) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (conversation_id, sender, message, message_type, json.dumps(metadata) if metadata else None)
        )
        message_id = cursor.fetchone()['id']
        cursor.execute("UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = %s", (conversation_id,))
        conn.commit()
        conn.close()
        return message_id

    def get_user_conversations(self, user_id, limit=50):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE user_id = %s AND is_active = TRUE ORDER BY updated_at DESC LIMIT %s",
            (user_id, limit)
        )
        conversations = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return conversations

    def get_conversation_messages(self, conversation_id, user_id, limit=200):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT m.sender, m.message, m.message_type, m.metadata, m.created_at
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.conversation_id = %s AND c.user_id = %s AND c.is_active = TRUE
            ORDER BY m.created_at ASC
            LIMIT %s
        ''', (conversation_id, user_id, limit))
        messages = []
        for row in cursor.fetchall():
            messages.append({
                'sender': row['sender'],
                'message': row['message'],
                'message_type': row['message_type'],
                'metadata': json.loads(row['metadata']) if row['metadata'] else None,
                'created_at': str(row['created_at']),
            })
        conn.close()
        return messages

    def update_conversation_title(self, conversation_id, user_id, title):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE conversations SET title = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s AND user_id = %s AND is_active = TRUE",
            (title, conversation_id, user_id)
        )
        updated = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return updated

    def delete_conversation(self, conversation_id, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM conversations WHERE id = %s AND user_id = %s", (conversation_id, user_id))
        if cursor.fetchone():
            cursor.execute("UPDATE conversations SET is_active = FALSE WHERE id = %s", (conversation_id,))
            conn.commit()
            conn.close()
            return True
        conn.close()
        return False

    # Activity Logs
    def log_activity(self, user_id, action, details=None, ip_address=None, user_agent=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO activity_logs (user_id, action, details, ip_address, user_agent) VALUES (%s, %s, %s, %s, %s)",
            (user_id, action, json.dumps(details) if details else None, ip_address, user_agent)
        )
        conn.commit()
        conn.close()

    def get_user_activities(self, user_id, limit=20):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT action, details, created_at FROM activity_logs WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
            (user_id, limit)
        )
        activities = []
        for row in cursor.fetchall():
            activities.append({
                'action': row['action'],
                'details': json.loads(row['details']) if row['details'] else None,
                'created_at': str(row['created_at']),
            })
        conn.close()
        return activities

    # Power BI Connections
    def save_powerbi_connection(self, user_id, tenant_id, client_id, connection_name=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO powerbi_connections (user_id, tenant_id, client_id, connection_name) VALUES (%s, %s, %s, %s) RETURNING id",
            (user_id, tenant_id, client_id, connection_name or f"Connection {datetime.now().strftime('%Y-%m-%d')}")
        )
        connection_id = cursor.fetchone()['id']
        conn.commit()
        conn.close()
        return connection_id

    def get_user_connections(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, tenant_id, client_id, connection_name, created_at FROM powerbi_connections WHERE user_id = %s AND is_active = TRUE ORDER BY created_at DESC",
            (user_id,)
        )
        connections = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return connections

    def get_stats(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        stats = {}
        cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE is_active = TRUE")
        stats['total_users'] = cursor.fetchone()['cnt']
        cursor.execute("SELECT COUNT(*) AS cnt FROM conversations WHERE is_active = TRUE")
        stats['total_conversations'] = cursor.fetchone()['cnt']
        cursor.execute("SELECT COUNT(*) AS cnt FROM messages")
        stats['total_messages'] = cursor.fetchone()['cnt']
        cursor.execute("SELECT COUNT(*) AS cnt FROM powerbi_connections WHERE is_active = TRUE")
        stats['total_connections'] = cursor.fetchone()['cnt']
        conn.close()
        return stats

    # Intent Logs
    def log_intent(self, conversation_id, message_id, user_message, intent, confidence, matched_keywords, processing_path):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO intent_logs (conversation_id, message_id, user_message, detected_intent, confidence, matched_keywords, processing_path) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (conversation_id, message_id, user_message, intent, confidence, json.dumps(matched_keywords), processing_path)
        )
        intent_log_id = cursor.fetchone()['id']
        conn.commit()
        conn.close()
        return intent_log_id

    def get_intent_logs(self, conversation_id, limit=50):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, user_message, detected_intent, confidence, matched_keywords, processing_path, created_at FROM intent_logs WHERE conversation_id = %s ORDER BY created_at DESC LIMIT %s",
            (conversation_id, limit)
        )
        logs = []
        for row in cursor.fetchall():
            logs.append({
                'id': row['id'],
                'user_message': row['user_message'],
                'detected_intent': row['detected_intent'],
                'confidence': row['confidence'],
                'matched_keywords': json.loads(row['matched_keywords']) if row['matched_keywords'] else [],
                'processing_path': row['processing_path'],
                'created_at': str(row['created_at']),
            })
        conn.close()
        return logs

    # MCP Interactions
    def log_mcp_interaction(self, conversation_id, message_id, intent_log_id, mcp_server,
                            tool_name, tool_arguments, tool_result, success=True,
                            error_message=None, execution_time_ms=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO mcp_interactions
                (conversation_id, message_id, intent_log_id, mcp_server, tool_name,
                 tool_arguments, tool_result, success, error_message, execution_time_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        ''', (conversation_id, message_id, intent_log_id, mcp_server, tool_name,
              json.dumps(tool_arguments) if tool_arguments else None,
              json.dumps(tool_result) if tool_result else None,
              success, error_message, execution_time_ms))
        mcp_log_id = cursor.fetchone()['id']
        conn.commit()
        conn.close()
        return mcp_log_id

    def get_mcp_interactions(self, conversation_id, limit=50):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, mcp_server, tool_name, tool_arguments, tool_result, success, error_message, execution_time_ms, created_at FROM mcp_interactions WHERE conversation_id = %s ORDER BY created_at DESC LIMIT %s",
            (conversation_id, limit)
        )
        logs = []
        for row in cursor.fetchall():
            logs.append({
                'id': row['id'],
                'mcp_server': row['mcp_server'],
                'tool_name': row['tool_name'],
                'tool_arguments': json.loads(row['tool_arguments']) if row['tool_arguments'] else None,
                'tool_result': json.loads(row['tool_result']) if row['tool_result'] else None,
                'success': bool(row['success']),
                'error_message': row['error_message'],
                'execution_time_ms': row['execution_time_ms'],
                'created_at': str(row['created_at']),
            })
        conn.close()
        return logs

    # Suggestions
    def save_suggestions(self, conversation_id, message_id, suggestions_list):
        conn = self.get_connection()
        cursor = conn.cursor()
        suggestion_ids = []
        for suggestion in suggestions_list:
            if isinstance(suggestion, dict):
                text = suggestion.get('text', suggestion.get('suggestion_text', ''))
                intent = suggestion.get('intent', suggestion.get('suggestion_intent'))
                priority = suggestion.get('priority', 3)
            else:
                text = str(suggestion)
                intent = None
                priority = 3
            cursor.execute(
                "INSERT INTO suggestions (conversation_id, message_id, suggestion_text, suggestion_intent, priority) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (conversation_id, message_id, text, intent, priority)
            )
            suggestion_ids.append(cursor.fetchone()['id'])
        conn.commit()
        conn.close()
        return suggestion_ids

    def suggestion_belongs_to_user(self, suggestion_id, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT s.id FROM suggestions s
            JOIN conversations c ON s.conversation_id = c.id
            WHERE s.id = %s AND c.user_id = %s
        ''', (suggestion_id, user_id))
        row = cursor.fetchone()
        conn.close()
        return row is not None

    def mark_suggestion_clicked(self, suggestion_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE suggestions SET was_clicked = TRUE, clicked_at = CURRENT_TIMESTAMP WHERE id = %s",
            (suggestion_id,)
        )
        conn.commit()
        conn.close()

    def get_suggestion_analytics(self, conversation_id=None, user_id=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if conversation_id:
            cursor.execute('''
                SELECT suggestion_text, suggestion_intent, COUNT(*) AS total,
                       SUM(CASE WHEN was_clicked THEN 1 ELSE 0 END) AS clicked
                FROM suggestions WHERE conversation_id = %s
                GROUP BY suggestion_text, suggestion_intent
            ''', (conversation_id,))
        elif user_id:
            cursor.execute('''
                SELECT s.suggestion_text, s.suggestion_intent, COUNT(*) AS total,
                       SUM(CASE WHEN s.was_clicked THEN 1 ELSE 0 END) AS clicked
                FROM suggestions s
                JOIN conversations c ON s.conversation_id = c.id
                WHERE c.user_id = %s
                GROUP BY s.suggestion_text, s.suggestion_intent
            ''', (user_id,))
        else:
            cursor.execute('''
                SELECT suggestion_text, suggestion_intent, COUNT(*) AS total,
                       SUM(CASE WHEN was_clicked THEN 1 ELSE 0 END) AS clicked
                FROM suggestions GROUP BY suggestion_text, suggestion_intent
            ''')
        analytics = []
        for row in cursor.fetchall():
            analytics.append({
                'suggestion_text': row['suggestion_text'],
                'suggestion_intent': row['suggestion_intent'],
                'total_shown': row['total'],
                'total_clicked': row['clicked'],
                'click_rate': (row['clicked'] / row['total'] * 100) if row['total'] > 0 else 0,
            })
        conn.close()
        return analytics

    # Token Usage
    def get_token_usage_per_user(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT
                u.id,
                u.username,
                u.email,
                COUNT(t.id)              AS api_calls,
                COALESCE(SUM(t.prompt_tokens), 0)      AS prompt_tokens,
                COALESCE(SUM(t.completion_tokens), 0)  AS completion_tokens,
                COALESCE(SUM(t.total_tokens), 0)       AS total_tokens,
                COALESCE(AVG(t.response_time_ms), 0)   AS avg_response_ms
            FROM users u
            LEFT JOIN token_usage t ON t.user_id = u.id
            WHERE u.is_active = TRUE
            GROUP BY u.id, u.username, u.email
            ORDER BY total_tokens DESC
        ''')
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                'id': r['id'],
                'username': r['username'],
                'email': r['email'],
                'api_calls': r['api_calls'],
                'prompt_tokens': int(r['prompt_tokens']),
                'completion_tokens': int(r['completion_tokens']),
                'total_tokens': int(r['total_tokens']),
                'avg_response_ms': round(float(r['avg_response_ms'])),
            }
            for r in rows
        ]

    def log_token_usage(self, user_id, conversation_id, message_id, model,
                        prompt_tokens, completion_tokens, total_tokens,
                        tool_calls_count=0, response_time_ms=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO token_usage
                (user_id, conversation_id, message_id, model,
                 prompt_tokens, completion_tokens, total_tokens,
                 tool_calls_count, response_time_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (user_id, conversation_id, message_id, model,
              prompt_tokens, completion_tokens, total_tokens,
              tool_calls_count, response_time_ms))
        conn.commit()
        conn.close()
