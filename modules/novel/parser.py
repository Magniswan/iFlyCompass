"""
小说章节解析器

提供两种解析模式：
1. 高级模式（默认）：使用 V3.1 锚点学习 + 统计验证算法，适用于大多数小说
2. 简单模式：使用基础正则匹配，作为备选方案

用法：
    from modules.novel.parser import parse_chapters
    
    chapters = parse_chapters(content)  # 默认使用高级模式
    chapters = parse_chapters(content, use_advanced=False)  # 使用简单模式
"""
import re
from utils import parse_chapters_advanced

CHAPTER_PATTERNS = [
    r'^第\s*[0-9]+\s*章',
    r'^第[一二三四五六七八九十百千]+章',
    r'^[0-9]+\.',
    r'^Chapter\s+[0-9]+',
    r'^CHAPTER\s+[0-9]+',
    r'^第\s*[0-9]+\s*章.*$',
]

def parse_chapters_simple(content):
    """简单章节解析 - 基础正则匹配
    
    Args:
        content: 小说全文内容
    
    Returns:
        list: 章节列表，每个元素包含 name 和 content
    """
    chapters = []
    lines = content.split('\n')
    
    chapter_patterns = [re.compile(pattern) for pattern in CHAPTER_PATTERNS]
    
    start_line = 0
    for i in range(min(20, len(lines))):
        if lines[i].strip() == '正文':
            for j in range(i + 1, len(lines)):
                if lines[j].strip():
                    start_line = j
                    break
            break
    
    current_chapter = None
    current_content = []
    
    for i in range(start_line, len(lines)):
        line = lines[i]
        line_stripped = line.strip()
        
        is_chapter_title = False
        for pattern in chapter_patterns:
            if pattern.match(line_stripped):
                is_chapter_title = True
                break
        
        if is_chapter_title:
            is_new_chapter = False
            if i == start_line:
                is_new_chapter = True
            elif i > 0 and lines[i-1].strip() == '':
                is_new_chapter = True
            
            if not is_new_chapter:
                is_new_chapter = True
            
            if is_new_chapter:
                if current_chapter is not None:
                    chapters.append({
                        'name': current_chapter,
                        'content': '\n'.join(current_content).strip()
                    })
                
                current_chapter = line_stripped
                current_content = []
        else:
            if current_chapter is not None:
                current_content.append(line)
    
    if current_chapter is not None:
        chapters.append({
            'name': current_chapter,
            'content': '\n'.join(current_content).strip()
        })
    
    if not chapters and content.strip():
        chapters.append({
            'name': '正文',
            'content': content.strip()
        })
    
    return chapters

def parse_chapters(content, use_advanced=True):
    """解析小说章节
    
    Args:
        content: 小说全文内容
        use_advanced: 是否使用高级解析模式（默认 True）
    
    Returns:
        list: 章节列表，每个元素包含 name 和 content
    """
    if not content or not content.strip():
        return []
    
    if use_advanced:
        try:
            chapters = parse_chapters_advanced(content)
            if chapters and len(chapters) > 0:
                return chapters
        except Exception as e:
            print(f"高级章节解析失败，回退到简单模式: {e}")
    
    return parse_chapters_simple(content)
