"""LLM客户端管理"""
import configparser
import os
import re
from openai import OpenAI
from src.AIquest.config import LLM_CONFIG, METRIC_CATEGORIES, METRIC_KEYWORDS,is_school_extraction_enabled


class LLMClient:
    """LLM客户端管理类"""
    
    def __init__(self, config_path=None):
        self.client = self._init_client(config_path)
        self.model_name = LLM_CONFIG['model_name']
        self.max_doc_length = LLM_CONFIG['max_doc_length']
    
    def _init_client(self, config_path):
        """初始化OpenAI客户端"""
        if config_path is None:
            current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(current_dir, 'config.ini')
        
        config = configparser.ConfigParser()
        api_key = None
        
        if os.path.exists(config_path):
            config.read(config_path)
            api_key = config.get('DEFAULT', 'DASHSCOPE_API_KEY', fallback=None)
        
        if not api_key:
            print("警告: 未在配置文件中找到 DASHSCOPE_API_KEY")
            return None
        
        return OpenAI(
            api_key=api_key,
            base_url=LLM_CONFIG['base_url']
        )
    
    def get_data_file_for_metric(self, metric_name, data_reader):
        """🔥 新增：获取指标对应的数据文件路径 🔥"""
        # 首先尝试查找已存在的文件
        existing_file = data_reader.find_existing_consolidated_file(metric_name)
        
        if existing_file:
            # 检查文件是否与当前模式匹配
            file_info = data_reader.get_consolidated_file_info(metric_name)
            if file_info:
                current_mode = "intelligent" if is_school_extraction_enabled() else "traditional"
                file_mode = file_info.get('processing_mode', 'unknown')
                
                if file_mode == current_mode:
                    print(f"  ✅ 找到匹配当前模式的文件: {file_info['file_name']}")
                    return existing_file
                else:
                    print(f"  ⚠️  文件模式不匹配 (文件:{file_mode}, 当前:{current_mode})，将重新生成")
        
        # 如果没有找到匹配的文件，生成新的整合数据
        print(f"  🔄 重新整合指标 '{metric_name}' 的数据...")
        return data_reader.consolidate_data_for_metric(metric_name)

    def get_answers_for_metric(self, questions_list, document_text, metric_name, data_reader=None):
        """为特定指标获取答案"""
        # 🔥 如果提供了data_reader，使用动态文件选择 🔥
        if data_reader and not document_text:
            data_file = self.get_data_file_for_metric(metric_name, data_reader)
            if data_file:
                document_text = data_reader.extract_text_content(data_file)
                print(f"  📄 从数据文件加载内容: {os.path.basename(data_file)}")
            else:
                print(f"  ❌ 无法获取指标 '{metric_name}' 的数据文件")
                return ["无法获取数据文件"] * len(questions_list)
        # 🔥 添加数据内容调试 🔥
        print(f"  📊 数据内容检查:")
        print(f"    - 数据长度: {len(document_text)} 字符")
        print(f"    - 数据前200字符: {document_text[:200]}...")
        
        # 🔥 检查关键学校信息 🔥
        if '中山大学' in document_text:
            print(f"    ✅ 数据中包含'中山大学'")
            # 找到中山大学相关的内容片段
            import re
            pattern = r'.{0,100}中山大学.{0,100}'
            matches = re.findall(pattern, document_text)
            for i, match in enumerate(matches[:3]):  # 只显示前3个匹配
                print(f"    📝 中山大学相关片段{i+1}: {match}")
        else:
            print(f"    ❌ 数据中不包含'中山大学'")
        
        # 🔥 检查双一流关键词 🔥
        keywords = ['双一流', '世界一流', '一流学科', '学科建设']
        found_keywords = []
        for keyword in keywords:
            if keyword in document_text:
                found_keywords.append(keyword)
        print(f"    🔑 找到关键词: {found_keywords}")
        
        # 如果没有找到关键信息，这可能是数据问题
        if '中山大学' not in document_text or not found_keywords:
            print(f"    ⚠️  警告: 数据中缺少关键信息，LLM可能无法找到正确答案")
        """为特定指标获取答案"""
        if not self.client:
            print("错误: OpenAI 客户端未初始化")
            return ["LLM客户端未初始化"] * len(questions_list)
        
        if not document_text or not document_text.strip():
            print("错误: 提供的文档内容为空")
            return ["文档内容为空"] * len(questions_list)
        
        # 截断文档内容
        truncated_document_text = self._truncate_document(document_text)
        
        # 根据指标类型定制系统提示
        system_prompt = self._get_system_prompt_for_metric(metric_name)
        
        # 初始化消息列表
        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': f"以下是关于 '{metric_name}' 的数据，请记住这些信息：\n\n{truncated_document_text}"},
            {'role': 'assistant', 'content': f"我已经分析了关于 '{metric_name}' 的数据，准备回答相关问题。"}
        ]
        
        try:
            # 确认文档已被接收
            print(f"  正在将 '{metric_name}' 相关数据发送给LLM...")
            completion = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                stream=False
            )
            
            if not completion.choices or not completion.choices[0].message:
                print("  警告: LLM未能正确接收文档内容")
                return ["LLM未能接收文档内容"] * len(questions_list)
            
            # 处理每个问题
            all_answers = []
            for question_text in questions_list:
                answer = self._process_single_question(messages.copy(), question_text, metric_name)
                all_answers.append(answer)
                
                # 更新消息历史
                messages.append({'role': 'user', 'content': self._get_question_prompt(question_text, metric_name)})
                messages.append({'role': 'assistant', 'content': answer})
            
            return all_answers
            
        except Exception as e:
            print(f"调用LLM API时发生错误: {e}")
            return [f"LLM API调用失败: {e}"] * len(questions_list)
    
    def _truncate_document(self, document_text):
        """截断文档内容"""
        if len(document_text) > self.max_doc_length:
            print(f"  文档内容过长 ({len(document_text)} chars)，将截断为 {self.max_doc_length} 字符")
            return document_text[:self.max_doc_length]
        return document_text
    
    def _get_system_prompt_for_metric(self, metric_name):
        """根据指标类型获取系统提示"""
        if metric_name in METRIC_CATEGORIES['subject_metrics']:
            if 'ESI' in metric_name:
                return """你是一个专门分析ESI学科排名数据的AI助手。
    ESI（Essential Science Indicators）是基于Web of Science数据库的学科排名系统。
    请在数据中准确查找和统计ESI相关学科信息。
    重点关注：进入ESI前1%或前1‰的学科名称和数量。
    只返回准确的数字答案。"""
            elif '双一流' in metric_name:
                return """你是一个专门分析国家双一流学科建设数据的AI助手。
    双一流指"世界一流大学和一流学科建设"，是国家重大教育政策。
    请在教育部政策数据中准确查找和统计双一流学科信息。
    重点关注：入选国家双一流建设的学科名称和数量。
    只返回准确的数字答案。"""
            elif '教育部评估A类' in metric_name:
                return """你是一个专门分析教育部学科评估数据的AI助手。
    教育部学科评估是对全国具有博士或硕士学位授予权的一级学科的整体水平评估。
    A类学科包括：A+、A、A-三个等级，代表该学科在全国排名前10%。
    请在学科评估数据中准确查找和统计A类学科信息。
    重点关注：获得A+、A、A-评级的学科名称和数量。
    只返回准确的数字答案。"""
            elif '软科' in metric_name:
                return """你是一个专门分析软科中国最好学科排名数据的AI助手。
    软科排名是重要的学科评价体系，前10%表示学科实力较强。
    请在数据中准确查找和统计软科排名相关信息。
    重点关注：进入软科排名前10%的学科名称和数量。
    只返回准确的数字答案。"""
            else:
                return """你是一个专门分析中国大学学科数据的AI助手。
    请准确统计和计算学科相关指标，重点关注学科数量。
    只返回准确的数字答案。"""
        
        elif metric_name in METRIC_CATEGORIES['major_metrics']:
            if '专业总数' in metric_name:
                return """你是一个专门分析高等教育本科专业数据的AI助手。
    请在教育部政策数据和专业数据中准确查找和统计本科专业总数。
    重点关注：该学校开设的所有本科专业数量。
    只返回准确的数字答案。"""
            elif '一流本科专业' in metric_name:
                return """你是一个专门分析一流本科专业建设点数据的AI助手。
    一流本科专业建设点分为国家级和省级两个层次，是教育部推进一流本科教育的重要举措。
    请在教育部政策数据中准确查找和统计一流本科专业建设点信息。
    重点关注：获批的国家级或省级一流本科专业建设点名称和数量。
    只返回准确的数字答案。"""
                #  新增学位点指标的系统提示 
            elif metric_name == '学术型硕士学位点':
                return """你是一个专门分析学术型硕士学位授权点数据的AI助手。
    学术型硕士学位点是指以培养学术研究人才为目标的硕士学位授权点，授予学术学位。
    请在学位点数据中准确查找和统计学术型硕士学位点信息。
    重点关注：获得学术型硕士学位授权的学科数量，通常按一级学科统计。
    注意区分学术型和专业型硕士学位点。
    只返回准确的数字答案。"""
            elif metric_name == '专业型硕士学位点':
                return """你是一个专门分析专业型硕士学位授权点数据的AI助手。
    专业型硕士学位点是指以培养应用型专门人才为目标的硕士学位授权点，授予专业学位。
    包括MBA、MPA、MPAcc、工程硕士、教育硕士等各类专业学位。
    请在学位点数据中准确查找和统计专业型硕士学位点信息。
    重点关注：获得专业型硕士学位授权的专业领域数量。
    注意区分学术型和专业型硕士学位点。
    只返回准确的数字答案。"""
            elif metric_name == '学术型博士学位点':
                return """你是一个专门分析学术型博士学位授权点数据的AI助手。
    学术型博士学位点是指以培养学术研究高层次人才为目标的博士学位授权点，授予学术学位。
    请在学位点数据中准确查找和统计学术型博士学位点信息。
    重点关注：获得学术型博士学位授权的学科数量，通常按一级学科统计。
    注意区分学术型和专业型博士学位点。
    只返回准确的数字答案。"""
            elif metric_name == '专业型博士学位点':
                return """你是一个专门分析专业型博士学位授权点数据的AI助手。
    专业型博士学位点是指以培养应用型高层次专门人才为目标的博士学位授权点，授予专业学位。
    包括工程博士、教育博士、临床医学博士等专业学位。
    请在学位点数据中准确查找和统计专业型博士学位点信息。
    重点关注：获得专业型博士学位授权的专业领域数量。
    注意区分学术型和专业型博士学位点。
    只返回准确的数字答案。"""
            else:
                return """你是一个专门分析中国大学本科专业数据的AI助手。
    请在教育部政策数据和专业数据中准确统计和计算本科专业相关指标。
    重点关注：专业数量统计。
    只返回准确的数字答案。"""
        
        # 🔥 新增教学相关指标的系统提示 🔥
        elif metric_name in METRIC_CATEGORIES['teaching_metrics']:
            if '教学成果奖' in metric_name:
                if '国家级' in metric_name:
                    return """你是一个专门分析国家级教学成果奖数据的AI助手。
    国家级教学成果奖是由国务院批准的教育教学研究和实践领域的最高奖项，每4年评选一次。
    请在教学成果数据中准确查找和统计国家级教学成果奖信息。
    重点关注：获得国家级教学成果奖的项目数量（包括特等奖、一等奖、二等奖）。
    只返回准确的数字答案。"""
                else:  # 省级教学成果奖
                    return """你是一个专门分析省级教学成果奖数据的AI助手。
    省级教学成果奖是由各省教育厅组织评选的教学成果奖项。
    请在教学成果数据中准确查找和统计省级教学成果奖信息。
    重点关注：获得省级教学成果奖的项目数量（包括特等奖、一等奖、二等奖）。
    只返回准确的数字答案。"""
            elif '青年教师教学竞赛' in metric_name:
                return """你是一个专门分析全国高校青年教师教学竞赛数据的AI助手。
    全国高校青年教师教学竞赛是由中国教科文卫体工会全国委员会主办的重要教学竞赛。
    请在教学竞赛数据中准确查找和统计青年教师教学竞赛获奖信息。
    重点关注：在全国高校青年教师教学竞赛中获奖的教师人数或项目数量。
    只返回准确的数字答案。"""
            elif '一流本科课程' in metric_name:
                if '国家级' in metric_name:
                    return """你是一个专门统计国家级一流本科课程数量的AI助手。

数据格式说明：
- 数据以"学校名："开头标识每个学校的课程段落
- 每个段落包含该学校的课程列表
- 课程信息格式：学校名 + 平台名 + 课程名称 + 负责人 + 团队成员
- 每次出现学校名称通常代表一门课程

统计规则：
1. 定位到询问学校的专属段落（"学校名："开头）
2. 在该段落中统计学校名称出现的次数
3. 每次出现不一定对应一门国家级一流本科课程，因为可能有重复的课程内容，你需要核对是否是重复的课程，去除掉重复的课程数

重要：只返回纯数字答案，不要任何解释或说明。如果没找到对应学校，返回"0"。

示例回答格式：
- 正确：25
- 错误：该学校有25门课程
- 错误：根据统计，数量为25"""
                else:  # 省级一流本科课程
                    return """你是一个专门分析省级一流本科课程数据的AI助手。
    省级一流本科课程是由各省教育厅认定的优质本科课程。
    请在课程数据中准确查找和统计省级一流本科课程信息。
    重点关注：获批省级一流本科课程的课程数量。
    只返回准确的数字答案。"""
            elif '智慧平台课程' in metric_name:
                if '国家级' in metric_name:
                    return """你是一个专门分析国家高等教育智慧平台课程数据的AI助手。
    国家高等教育智慧平台是教育部推出的在线教育平台，汇聚优质课程资源。
    请在智慧平台数据中准确查找和统计国家级智慧平台课程信息。
    重点关注：上线国家高等教育智慧平台的课程数量。
    只返回准确的数字答案。"""
                else:  # 省级智慧平台课程
                    return """你是一个专门分析省级高等教育智慧平台课程数据的AI助手。
    省级高等教育智慧平台是各省推出的在线教育平台。
    请在智慧平台数据中准确查找和统计省级智慧平台课程信息。
    重点关注：上线省级高等教育智慧平台的课程数量。
    只返回准确的数字答案。"""
            else:
                return """你是一个专门分析中国大学教学相关数据的AI助手。
    请准确统计和计算教学相关指标，重点关注教学成果、课程、竞赛等数量。
    只返回准确的数字答案。"""
        
        else:
            return "你是一个专门分析中国大学数据的AI助手。请准确统计和计算相关指标。只返回准确的数字答案。"
    
    def _get_question_prompt(self, question_text, metric_name):
        """根据指标类型获取优化的问题提示"""
        # ...existing code...
        base_prompt = f"问题：{question_text}\n\n"
        
        # 获取指标关键词
        keywords = METRIC_KEYWORDS.get(metric_name, [])
        keywords_str = "、".join(keywords) if keywords else metric_name
        
        # 🔥 ESI指标处理（已存在，保持不变）🔥
        if metric_name == 'ESI前1%学科数量':
            return base_prompt + f"""请在数据中查找ESI相关信息，重点关注以下关键词：{keywords_str}。
    查找进入ESI前1%的学科，并统计数量。
    如果数据中明确提到ESI前1%学科，请统计具体数量。
    只返回数字答案，如果找不到相关信息，请回答"0"。"""
        
        elif metric_name == 'ESI前1‰学科数量':
            return base_prompt + f"""请在数据中查找ESI相关信息，重点关注以下关键词：{keywords_str}。
    查找进入ESI前1‰（千分之一）的学科，并统计数量。
    如果数据中明确提到ESI前1‰学科，请统计具体数量。
    只返回数字答案，如果找不到相关信息，请回答"0"。"""
        
        elif metric_name == '国家双一流学科数量':
            return base_prompt + f"""请在教育部政策数据中查找双一流相关信息，重点关注以下关键词：{keywords_str}。
    查找入选国家"双一流"学科建设的学科，并统计数量。
    注意区分"双一流大学"和"双一流学科"，这里只统计学科数量。
    只返回数字答案，如果找不到相关信息，请回答"0"。"""
        
        elif metric_name == '教育部评估A类学科数量':
            return base_prompt + f"""请在学科评估数据中查找教育部评估相关信息，重点关注以下关键词：{keywords_str}。
    查找在教育部学科评估中获得A类评级（A+、A、A-）的学科，并统计数量。
    注意：
    - A+表示前2%或前2名（该学科全国排名最高）
    - A表示前2%-5%
    - A-表示前5%-10%
    - 这三个等级统称为A类学科
    如果数据中明确提到学科评估A+、A、A-等级，请统计具体数量。
    只返回数字答案，如果找不到相关信息，请回答"0"。"""
        
        # 🔥 新增软科指标处理 🔥
        elif metric_name == '软科中国最好学科排名前10%学科数量':
            return base_prompt + f"""请在数据中查找软科排名相关信息，重点关注以下关键词：{keywords_str}。
    查找在软科"中国最好学科"排名中进入前10%的学科，并统计数量。
    重点查找：排名百分位前10%的学科，或明确标注为"前10%"的学科。
    只返回数字答案，如果找不到相关信息，请回答"0"。"""
        
        elif metric_name == '本科专业总数':
            return base_prompt + f"""请在教育部政策数据和专业数据中查找本科专业相关信息，重点关注以下关键词：{keywords_str}。
    统计该学校的本科专业总数，包括所有本科专业。
    查找专业目录、专业设置等相关信息，统计开设的本科专业数量。
    只返回数字答案，如果找不到相关信息，请回答"0"。"""
        
        elif metric_name == '国家级一流本科专业建设点':
            return base_prompt + f"""请在教育部政策数据中查找一流本科专业相关信息，重点关注以下关键词：{keywords_str}。
    查找获批国家级一流本科专业建设点的专业，并统计数量。
    注意区分国家级和省级，这里只统计国家级。
    只返回数字答案，如果找不到相关信息，请回答"0"。"""
        
        elif metric_name == '省级一流本科专业建设点':
            return base_prompt + f"""请在教育部政策数据中查找一流本科专业相关信息，重点关注以下关键词：{keywords_str}。
    查找获批省级一流本科专业建设点的专业，并统计数量。
    注意区分国家级和省级，这里只统计省级（或省一流）。
    只返回数字答案，如果找不到相关信息，请回答"0"。"""
        
        # 🔥 新增教学成果奖指标处理 🔥
        elif metric_name == '国家级教学成果奖':
            return base_prompt + f"""请在教学成果数据中查找国家级教学成果奖相关信息，重点关注以下关键词：{keywords_str}。
    查找获得国家级教学成果奖的项目，并统计数量。
    包括：国家级教学成果奖特等奖、一等奖、二等奖。
    只返回数字答案，如果找不到相关信息，请回答"0"。"""
        
        elif metric_name == '省级教学成果奖':
            return base_prompt + f"""请在教学成果数据中查找省级教学成果奖相关信息，重点关注以下关键词：{keywords_str}。
    查找获得省级教学成果奖的项目，并统计数量。
    包括：省级教学成果奖特等奖、一等奖、二等奖。
    只返回数字答案，如果找不到相关信息，请回答"0"。"""
        
        elif metric_name == '全国高校青年教师教学竞赛':
            return base_prompt + f"""请在教学竞赛数据中查找青年教师教学竞赛相关信息，重点关注以下关键词：{keywords_str}。
    查找在全国高校青年教师教学竞赛中获奖的情况，并统计获奖数量。
    包括：全国一等奖、二等奖、三等奖等各级奖项。
    只返回数字答案，如果找不到相关信息，请回答"0"。"""
        elif metric_name == '学术型硕士学位点':
            return base_prompt + f"""请在学位点数据中查找学术型硕士学位点相关信息，重点关注以下关键词：{keywords_str}。
    查找该学校获得的学术型硕士学位授权点，并统计数量。
    重点查找：学术型硕士、学术硕士、硕士学位授权点（学术型）等信息。
    注意区分学术型和专业型，只统计学术型硕士学位点。
    通常按一级学科进行统计。
    只返回数字答案，如果找不到相关信息，请回答"0"。"""
        
        elif metric_name == '专业型硕士学位点':
            return base_prompt + f"""请在学位点数据中查找专业型硕士学位点相关信息，重点关注以下关键词：{keywords_str}。
    查找该学校获得的专业型硕士学位授权点，并统计数量。
    重点查找：专业型硕士、专业硕士、MBA、MPA、MPAcc、工程硕士、教育硕士等专业学位信息。
    注意区分学术型和专业型，只统计专业型硕士学位点。
    按专业学位类别进行统计。
    只返回数字答案，如果找不到相关信息，请回答"0"。"""
        
        elif metric_name == '学术型博士学位点':
            return base_prompt + f"""请在学位点数据中查找学术型博士学位点相关信息，重点关注以下关键词：{keywords_str}。
    查找该学校获得的学术型博士学位授权点，并统计数量。
    重点查找：学术型博士、学术博士、博士学位授权点（学术型）等信息。
    注意区分学术型和专业型，只统计学术型博士学位点。
    通常按一级学科进行统计。
    只返回数字答案，如果找不到相关信息，请回答"0"。"""
        
        elif metric_name == '专业型博士学位点':
            return base_prompt + f"""请在学位点数据中查找专业型博士学位点相关信息，重点关注以下关键词：{keywords_str}。
    查找该学校获得的专业型博士学位授权点，并统计数量。
    重点查找：专业型博士、专业博士、工程博士、教育博士、临床医学博士等专业学位信息。
    注意区分学术型和专业型，只统计专业型博士学位点。
    按专业学位类别进行统计。
    只返回数字答案，如果找不到相关信息，请回答"0"。"""
        
        # 🔥 新增一流课程指标处理 🔥
        elif metric_name == '国家级一流本科课程':
            return base_prompt + f"""数据统计说明：
- 数据以"学校名："开头标识每个学校的课程段落
- 在询问学校的段落中，统计该学校名称出现的次数
- 每次学校名称出现 = 一门国家级一流本科课程

统计步骤：
1. 找到"[询问的学校名]："开头的段落
2. 统计该段落中该学校名称的出现次数
3. 返回统计数字

注意：
- 只统计询问学校自己的课程
- 不要统计其他学校的课程
- 必须只返回纯数字答案
- 找不到对应学校信息时返回"0"

现在请统计并只返回数字答案："""
        
        elif metric_name == '省级一流本科课程':
            return base_prompt + f"""请在课程数据中查找省级一流本科课程相关信息，重点关注以下关键词：{keywords_str}。
    查找获批省级一流本科课程的课程，并统计数量。
    包括各种类型的省级一流本科课程。
    只返回数字答案，如果找不到相关信息，请回答"0"。"""
        
        # 🔥 新增智慧平台课程指标处理 🔥
        elif metric_name == '国家级高等教育智慧平台课程':
            return base_prompt + f"""请在智慧平台数据中查找国家级智慧平台课程相关信息，重点关注以下关键词：{keywords_str}。
    查找上线国家高等教育智慧平台的课程，并统计数量。
    重点查找：在国家智慧教育平台、国家高等教育智慧平台等上线的课程。
    只返回数字答案，如果找不到相关信息，请回答"0"。"""
        
        elif metric_name == '省级高等教育智慧平台课程':
            return base_prompt + f"""请在智慧平台数据中查找省级智慧平台课程相关信息，重点关注以下关键词：{keywords_str}。
    查找上线省级高等教育智慧平台的课程，并统计数量。
    重点查找：在省级智慧教育平台上线的课程。
    只返回数字答案，如果找不到相关信息，请回答"0"。"""
        
        else:
            return base_prompt + f"请在数据中查找 {metric_name} 相关信息并统计数量。只返回数字答案。如果找不到，请回答'0'。"
    
    def _process_single_question(self, messages, question_text, metric_name):
        """处理单个问题"""
        print(f"  处理问题: {question_text}")
        
        current_messages = messages.copy()
        question_prompt = self._get_question_prompt(question_text, metric_name)
        current_messages.append({'role': 'user', 'content': question_prompt})
        
        # 获取答案
        question_completion = self.client.chat.completions.create(
            model=self.model_name,
            messages=current_messages,
            stream=True,
            stream_options={"include_usage": True}
        )
        
        # 收集回答
        ai_response = ""
        for chunk in question_completion:
            if chunk.choices and len(chunk.choices) > 0 and chunk.choices[0].delta and chunk.choices[0].delta.content:
                ai_response += chunk.choices[0].delta.content
        
        ai_response = ai_response.strip()
        print(f"    LLM回答: {ai_response}")
        
        # 解析答案
        return self._parse_answer(ai_response, metric_name)
    
    def _parse_answer(self, ai_response, metric_name):
        """解析AI回答，针对指标优化"""
        # 查找数字
        numbers = re.findall(r'\d+', ai_response)
        if numbers:
            # 对于某些指标，可能需要特殊处理
            if metric_name in ['ESI前1%学科数量', 'ESI前1‰学科数量']:
                # ESI指标通常数量不会太大，选择最小的合理数字
                valid_numbers = [int(n) for n in numbers if int(n) <= 50]  # ESI学科数一般不超过50
                if valid_numbers:
                    return str(min(valid_numbers))
            elif metric_name == '教育部评估A类学科数量':
                # 教育部评估A类学科数量通常不会太大，一般不超过30个
                valid_numbers = [int(n) for n in numbers if int(n) <= 30]
                if valid_numbers:
                    return str(min(valid_numbers))
            # 🔥 新增软科指标的特殊处理 🔥
            elif metric_name == '软科中国最好学科排名前10%学科数量':
                # 软科前10%学科数量通常不会太大，一般不超过40个
                valid_numbers = [int(n) for n in numbers if int(n) <= 40]
                if valid_numbers:
                    return str(min(valid_numbers))
            # 🔥 新增专业相关指标的特殊处理 🔥
            elif metric_name == '本科专业总数':
                # 本科专业总数通常在20-200之间
                valid_numbers = [int(n) for n in numbers if 5 <= int(n) <= 300]
                if valid_numbers:
                    return str(max(valid_numbers))  # 专业总数取较大值更合理
            elif metric_name in ['国家级一流本科专业建设点', '省级一流本科专业建设点']:
                # 一流专业建设点数量通常不会太大
                valid_numbers = [int(n) for n in numbers if int(n) <= 100]
                if valid_numbers:
                    return str(min(valid_numbers))
            # 🔥 新增教学相关指标的特殊处理 🔥
            elif metric_name in ['国家级教学成果奖', '省级教学成果奖']:
                # 教学成果奖数量通常较少
                valid_numbers = [int(n) for n in numbers if int(n) <= 50]
                if valid_numbers:
                    return str(min(valid_numbers))
            elif metric_name == '全国高校青年教师教学竞赛':
                # 青年教师教学竞赛获奖数量通常较少
                valid_numbers = [int(n) for n in numbers if int(n) <= 30]
                if valid_numbers:
                    return str(min(valid_numbers))
            elif metric_name in ['国家级一流本科课程', '省级一流本科课程']:
                # 一流课程数量可能较多
                valid_numbers = [int(n) for n in numbers if int(n) <= 200]
                if valid_numbers:
                    return str(min(valid_numbers))
            elif metric_name in ['国家级高等教育智慧平台课程', '省级高等教育智慧平台课程']:
                # 智慧平台课程数量可能较多
                valid_numbers = [int(n) for n in numbers if int(n) <= 500]
                if valid_numbers:
                    return str(min(valid_numbers))
                # 🔥 新增学位点指标的特殊处理 🔥
            elif metric_name in ['学术型硕士学位点', '专业型硕士学位点']:
                # 硕士学位点数量通常在0-50之间
                valid_numbers = [int(n) for n in numbers if int(n) <= 50]
                if valid_numbers:
                    return str(min(valid_numbers))
            elif metric_name in ['学术型博士学位点', '专业型博士学位点']:
                # 博士学位点数量通常在0-30之间（博士点相对较少）
                valid_numbers = [int(n) for n in numbers if int(n) <= 30]
                if valid_numbers:
                    return str(min(valid_numbers))
            
            return numbers[0]
        
        # 检查是否明确说明未找到或为0
        if any(keyword in ai_response for keyword in ["未找到", "无法找到", "没有找到", "不存在", "为0", "是0", "等于0"]):
            return "0"
        
        # 默认情况
        print(f"    警告: 无法从回答 '{ai_response}' 中提取数字，标记为0")
        return "0"