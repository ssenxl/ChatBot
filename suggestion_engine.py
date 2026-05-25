from typing import List, Dict, Optional
from dataclasses import dataclass
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class Suggestion:
    text: str
    intent: str
    priority: int  # 1-5, higher = more important
    context: Optional[str] = None


class SuggestionEngine:
    def __init__(self):
        self.suggestion_templates = self._load_suggestion_templates()
        
    def _load_suggestion_templates(self) -> Dict:
        """โหลด suggestion templates สำหรับแต่ละ context"""
        return {
            'greeting': [
                Suggestion('ข้อมูลเครื่องจักร', 'machine_capacity', 5),
                Suggestion('ข้อมูล Item', 'item_data', 5),
                Suggestion('ข้อมูลแผนทอ', 'knitting_plan', 5),
                Suggestion('ดูรายงาน Power BI', 'powerbi_report', 4),
            ],
            'machine_capacity': [
                Suggestion('ดูเครื่องจักรทั้งหมด', 'machine_capacity', 5, 'detail'),
                Suggestion('ตรวจสอบสถานะเครื่อง', 'machine_capacity', 4, 'status'),
                Suggestion('ดูแผนการผลิต', 'knitting_plan', 4),
                Suggestion('วิเคราะห์ประสิทธิภาพ', 'data_analysis', 3),
            ],
            'item_data': [
                Suggestion('ค้นหา item เฉพาะ', 'item_data', 5, 'search'),
                Suggestion('ดูตามหมวดหมู่', 'item_data', 4, 'category'),
                Suggestion('ตรวจสอบสต็อก', 'item_data', 4, 'stock'),
                Suggestion('ดูแผนการใช้งาน', 'knitting_plan', 3),
            ],
            'knitting_plan': [
                Suggestion('ดูแผนสัปดาห์หน้า', 'knitting_plan', 5, 'next_week'),
                Suggestion('ดูตามเครื่องจักร', 'knitting_plan', 4, 'by_machine'),
                Suggestion('สรุปแผนประจำเดือน', 'data_analysis', 4),
                Suggestion('ตรวจสอบ capacity', 'machine_capacity', 3),
            ],
            'powerbi_report': [
                Suggestion('ดูรายงานอื่น', 'powerbi_report', 5, 'other_reports'),
                Suggestion('ดู workspace ทั้งหมด', 'powerbi_report', 4, 'workspaces'),
                Suggestion('วิเคราะห์ข้อมูล', 'data_analysis', 4),
                Suggestion('ส่งออกรายงาน', 'powerbi_report', 3, 'export'),
            ],
            'data_analysis': [
                Suggestion('วิเคราะห์เพิ่มเติม', 'data_analysis', 5, 'deep_dive'),
                Suggestion('สรุปผลการวิเคราะห์', 'data_analysis', 4, 'summary'),
                Suggestion('ส่งออกข้อมูล', 'data_analysis', 3, 'export'),
                Suggestion('ดูข้อมูลต้นทาง', 'item_data', 3),
            ],
            'unknown': [
                Suggestion('ข้อมูลเครื่องจักร', 'machine_capacity', 5),
                Suggestion('ข้อมูล Item', 'item_data', 5),
                Suggestion('ข้อมูล Capacity', 'machine_capacity', 4),
                Suggestion('ข้อมูลแผนทอ', 'knitting_plan', 4),
            ],
        }
    
    def generate_suggestions(
        self, 
        current_intent: str, 
        conversation_history: Optional[List[Dict]] = None,
        user_context: Optional[Dict] = None
    ) -> List[str]:
        """
        สร้าง smart suggestions ตาม context ปัจจุบัน
        
        Args:
            current_intent: Intent ปัจจุบันที่ตรวจพบ
            conversation_history: ประวัติการสนทนา (optional)
            user_context: ข้อมูล context ของผู้ใช้ (optional)
            
        Returns:
            List of suggestion strings
        """
        # ดึง base suggestions จาก intent
        base_suggestions = self.suggestion_templates.get(
            current_intent, 
            self.suggestion_templates['unknown']
        )
        
        # ปรับ suggestions ตาม conversation history
        if conversation_history:
            base_suggestions = self._adjust_by_history(base_suggestions, conversation_history)
        
        # ปรับ suggestions ตาม user context
        if user_context:
            base_suggestions = self._adjust_by_user_context(base_suggestions, user_context)
        
        # เรียงตาม priority และแปลงเป็น text
        sorted_suggestions = sorted(base_suggestions, key=lambda x: x.priority, reverse=True)
        
        # Return top 4 suggestions
        return [s.text for s in sorted_suggestions[:4]]
    
    def _adjust_by_history(
        self, 
        suggestions: List[Suggestion], 
        history: List[Dict]
    ) -> List[Suggestion]:
        """ปรับ suggestions ตามประวัติการสนทนา"""
        if not history or len(history) < 2:
            return suggestions
        
        # ดึง intents ที่เคยถามไปแล้ว
        recent_intents = set()
        for msg in history[-5:]:  # ดู 5 ข้อความล่าสุด
            if msg.get('metadata', {}).get('intent'):
                recent_intents.add(msg['metadata']['intent'])
        
        # ลด priority ของ suggestions ที่เพิ่งถามไป
        adjusted = []
        for suggestion in suggestions:
            new_suggestion = Suggestion(
                text=suggestion.text,
                intent=suggestion.intent,
                priority=suggestion.priority,
                context=suggestion.context
            )
            
            # ถ้าเพิ่งถามไปแล้ว ลด priority
            if suggestion.intent in recent_intents:
                new_suggestion.priority = max(1, suggestion.priority - 2)
            
            adjusted.append(new_suggestion)
        
        return adjusted
    
    def _adjust_by_user_context(
        self, 
        suggestions: List[Suggestion], 
        context: Dict
    ) -> List[Suggestion]:
        """ปรับ suggestions ตาม user context (เช่น role, preferences)"""
        user_role = context.get('role', 'user')
        
        # ถ้าเป็น admin อาจจะมี suggestions พิเศษ
        if user_role == 'admin':
            # เพิ่ม priority ให้กับ data analysis
            adjusted = []
            for suggestion in suggestions:
                new_suggestion = Suggestion(
                    text=suggestion.text,
                    intent=suggestion.intent,
                    priority=suggestion.priority,
                    context=suggestion.context
                )
                
                if suggestion.intent == 'data_analysis':
                    new_suggestion.priority = min(5, suggestion.priority + 1)
                
                adjusted.append(new_suggestion)
            
            return adjusted
        
        return suggestions
    
    def get_contextual_followup(self, intent: str, response_data: Optional[Dict] = None) -> List[str]:
        """
        สร้าง follow-up suggestions ที่เฉพาะเจาะจงตาม response data
        
        Args:
            intent: Intent ที่เพิ่งประมวลผล
            response_data: ข้อมูลที่ได้จาก response
            
        Returns:
            List of follow-up suggestion strings
        """
        followups = []
        
        if intent == 'machine_capacity' and response_data:
            machines = response_data.get('machines', [])
            if machines:
                # สร้าง suggestions สำหรับเครื่องจักรเฉพาะ
                for machine in machines[:2]:
                    followups.append(f"ดูรายละเอียด {machine.get('name', 'เครื่องจักร')}")
        
        elif intent == 'item_data' and response_data:
            items = response_data.get('items', [])
            if items:
                categories = set(item.get('category') for item in items if item.get('category'))
                for category in list(categories)[:2]:
                    followups.append(f"ดู items ในหมวด {category}")
        
        elif intent == 'knitting_plan' and response_data:
            plans = response_data.get('plans', [])
            if plans:
                # สร้าง suggestions ตามวันที่
                dates = set(plan.get('date') for plan in plans if plan.get('date'))
                for date in list(dates)[:2]:
                    followups.append(f"ดูแผนวันที่ {date}")
        
        # ถ้าไม่มี specific followups ให้ใช้ general suggestions
        if not followups:
            return self.generate_suggestions(intent)
        
        return followups[:4]
    
    def get_quick_actions(self) -> List[Dict[str, str]]:
        """
        ดึง quick actions สำหรับแสดงเป็นปุ่มด่วน
        
        Returns:
            List of quick action dictionaries
        """
        return [
            {
                'text': 'ข้อมูลเครื่องจักร',
                'intent': 'machine_capacity',
                'icon': 'fa-industry',
                'color': 'blue'
            },
            {
                'text': 'ข้อมูล Item',
                'intent': 'item_data',
                'icon': 'fa-box',
                'color': 'indigo'
            },
            {
                'text': 'ข้อมูล Capacity',
                'intent': 'machine_capacity',
                'icon': 'fa-chart-pie',
                'color': 'amber'
            },
            {
                'text': 'ข้อมูลแผนทอ',
                'intent': 'knitting_plan',
                'icon': 'fa-clipboard-list',
                'color': 'rose'
            },
        ]
    
    def analyze_conversation_flow(self, history: List[Dict]) -> Dict[str, any]:
        """
        วิเคราะห์ flow ของการสนทนาเพื่อปรับปรุง suggestions
        
        Returns:
            Analysis results
        """
        if not history:
            return {'total_messages': 0, 'intents': {}, 'avg_confidence': 0}
        
        intents = {}
        confidences = []
        
        for msg in history:
            metadata = msg.get('metadata', {})
            intent = metadata.get('intent')
            confidence = metadata.get('confidence', 0)
            
            if intent:
                intents[intent] = intents.get(intent, 0) + 1
                confidences.append(confidence)
        
        return {
            'total_messages': len(history),
            'intents': intents,
            'avg_confidence': sum(confidences) / len(confidences) if confidences else 0,
            'most_common_intent': max(intents.items(), key=lambda x: x[1])[0] if intents else None
        }


# Singleton instance
_suggestion_engine_instance = None

def get_suggestion_engine() -> SuggestionEngine:
    """ดึง SuggestionEngine instance"""
    global _suggestion_engine_instance
    if _suggestion_engine_instance is None:
        _suggestion_engine_instance = SuggestionEngine()
    return _suggestion_engine_instance
