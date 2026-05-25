import json
import re
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class IntentResult:
    intent: str
    confidence: float
    matched_keywords: List[str]
    processing_path: str  # 'llm', 'hybrid', 'intent'
    mcp_server: Optional[str] = None


class IntentDetector:
    def __init__(self, config_path: str = 'mcp_config.json'):
        self.config_path = config_path
        self.intents_config = self._load_intents()
        
        # Confidence thresholds for processing paths
        self.HIGH_CONFIDENCE = 0.75  # Direct intent mode
        self.MEDIUM_CONFIDENCE = 0.50  # Hybrid processing
        # Below MEDIUM_CONFIDENCE = LLM mode
        
    def _load_intents(self) -> Dict:
        """โหลด intent configuration"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get('intents', {})
        except Exception as e:
            logger.error(f"Failed to load intents config: {e}")
            return {}
    
    def detect_intent(self, user_message: str) -> IntentResult:
        """
        ตรวจจับ intent จากข้อความของผู้ใช้
        
        Returns:
            IntentResult with intent, confidence, and processing path
        """
        message_lower = user_message.lower().strip()
        
        # คำนวณ confidence score สำหรับแต่ละ intent
        intent_scores = {}
        
        for intent_name, intent_config in self.intents_config.items():
            score, matched = self._calculate_intent_score(
                message_lower, 
                intent_config.get('keywords', [])
            )
            
            if score > 0:
                intent_scores[intent_name] = {
                    'score': score,
                    'matched_keywords': matched,
                    'mcp_server': intent_config.get('mcp_server'),
                    'threshold': intent_config.get('confidence_threshold', 0.7)
                }
        
        # หา intent ที่มี score สูงสุด
        if not intent_scores:
            return self._create_default_result(user_message)
        
        best_intent = max(intent_scores.items(), key=lambda x: x[1]['score'])
        intent_name = best_intent[0]
        intent_data = best_intent[1]
        
        # กำหนด processing path ตาม confidence
        confidence = intent_data['score']
        processing_path = self._determine_processing_path(confidence)
        
        logger.info(f"Detected intent: {intent_name} (confidence: {confidence:.2f}, path: {processing_path})")
        
        return IntentResult(
            intent=intent_name,
            confidence=confidence,
            matched_keywords=intent_data['matched_keywords'],
            processing_path=processing_path,
            mcp_server=intent_data.get('mcp_server')
        )
    
    @staticmethod
    def _is_thai(text: str) -> bool:
        return any('฀' <= c <= '๿' for c in text)

    def _calculate_intent_score(self, message: str, keywords: List[str]) -> Tuple[float, List[str]]:
        """
        คำนวณ score สำหรับ intent
        - ภาษาไทย: ใช้ substring match (\\b ไม่รองรับ Thai)
        - ภาษาอังกฤษ: ใช้ word boundary
        - 1 keyword match = 0.8 (intent mode), 2+ = 1.0
        """
        if not keywords:
            return 0.0, []

        matched_keywords = []

        for keyword in keywords:
            keyword_lower = keyword.lower()
            if self._is_thai(keyword_lower):
                if keyword_lower in message:
                    matched_keywords.append(keyword)
            else:
                pattern = r'\b' + re.escape(keyword_lower) + r'\b'
                if re.search(pattern, message):
                    matched_keywords.append(keyword)

        total_matches = len(matched_keywords)
        if total_matches == 0:
            return 0.0, []

        # 1 match → 0.8 (intent mode), แต่ละ match เพิ่ม 0.1 สูงสุด 1.0
        score = min(1.0, 0.8 + (total_matches - 1) * 0.1)
        return score, matched_keywords
    
    def _determine_processing_path(self, confidence: float) -> str:
        """
        กำหนด processing path ตาม confidence score
        
        - High confidence (>= 0.75): Intent Mode - ใช้ intent-based response โดยตรง
        - Medium confidence (0.50-0.75): Hybrid - ผสม intent + LLM
        - Low confidence (< 0.50): LLM Mode - ให้ LLM ประมวลผลเต็มรูปแบบ
        """
        if confidence >= self.HIGH_CONFIDENCE:
            return 'intent'
        elif confidence >= self.MEDIUM_CONFIDENCE:
            return 'hybrid'
        else:
            return 'llm'
    
    def _create_default_result(self, message: str) -> IntentResult:
        """สร้าง result เริ่มต้นเมื่อไม่พบ intent ที่ชัดเจน"""
        # ตรวจสอบว่าเป็นคำทักทายหรือไม่
        greetings = ['สวัสดี', 'hello', 'hi', 'หวัดดี', 'ดีครับ', 'ดีค่ะ']
        message_lower = message.lower()
        
        for greeting in greetings:
            if greeting in message_lower:
                return IntentResult(
                    intent='greeting',
                    confidence=0.9,
                    matched_keywords=[greeting],
                    processing_path='intent',
                    mcp_server=None
                )
        
        # ไม่พบ intent ที่ชัดเจน -> ใช้ LLM
        return IntentResult(
            intent='unknown',
            confidence=0.0,
            matched_keywords=[],
            processing_path='llm',
            mcp_server=None
        )
    
    def get_intent_description(self, intent_name: str) -> str:
        """ดึงคำอธิบายของ intent"""
        intent_descriptions = {
            'machine': 'ข้อมูลเครื่องจักร',
            'cap_ava': 'กำลังการผลิตที่ว่าง (CAP AVA)',
            'knit_plan': 'แผนการทอ (Knit Plan)',
            'booking': 'ข้อมูลการจอง (Booking Master)',
            'greeting': 'การทักทายและเริ่มต้นบทสนทนา',
            'unknown': 'อื่นๆ (Other)'
        }
        return intent_descriptions.get(intent_name, 'ไม่ทราบ')
    
    def get_available_intents(self) -> List[Dict[str, str]]:
        """ดึงรายการ intents ทั้งหมดที่มี"""
        intents = []
        for intent_name in self.intents_config.keys():
            intents.append({
                'name': intent_name,
                'description': self.get_intent_description(intent_name)
            })
        return intents


# Singleton instance
_intent_detector_instance = None

def get_intent_detector() -> IntentDetector:
    """ดึง IntentDetector instance"""
    global _intent_detector_instance
    if _intent_detector_instance is None:
        _intent_detector_instance = IntentDetector()
    return _intent_detector_instance
