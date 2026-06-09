import time
import json
import asyncio
import pandas as pd
import akshare as ak
from openai import OpenAI
from playwright.async_api import async_playwright

# 配置 API 凭证
api_key = "YOUR_API_KEY"
base_url = "openai_sdk_base_url" #such as https://generativelanguage.googleapis.com/v1beta/openai/
model = "model_name" #such as gemini-flash-lite-latest

def call_llm_analyzer(prompt: str, model: str = model, json_mode: bool = True) -> dict:
    """
    封装 OpenAI SDK 调用大模型的函数
    """
    client = OpenAI(
        api_key=api_key,
        base_url=base_url 
    )

    messages = [
        {
            "role": "system", 
            "content": "你是一个严谨的数据审计专家，必须严格按照要求的 JSON 结构进行回复。"
        },
        {
            "role": "user", 
            "content": prompt
        }
    ]

    extra_params = {}
    if json_mode:
        extra_params["response_format"] = {"type": "json_object"}

    try:
        print(f"🚀 正在调用大模型 ({model}) 进行团队风控审计与量化评分...")
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            **extra_params
        )
        
        raw_content = response.choices[0].message.content
        if json_mode:
            return json.loads(raw_content)
        else:
            return {"raw_text": raw_content}
    except Exception as e:
        print(f"❌ 调用大模型失败: {e}")
        return {}


async def generate_prompt(page, target_url, company_name):
    """
    通过复用已有的 page 实例来抓取数据，避免重复启动浏览器
    """
    print(f"📡 正在访问网页: {target_url} ...")
    try:
        await page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
        target_selector = "div.glcjj_table"
        await page.wait_for_selector(target_selector, timeout=5000)
    except Exception as e:
        print(f"⚠️ 无法加载页面或未找到元素 {target_url}: {e}")
        return None

    # 在浏览器内部清洗数据
    cleaned_data = await page.evaluate('''
        () => {
            const tbodyElements = document.querySelectorAll('div.glcjj_table table tbody');
            let resultText = "";
            
            tbodyElements.forEach((tbody) => {
                const nameEl = tbody.querySelector('b.tips-personalname');
                const name = nameEl ? nameEl.textContent.trim() : "未知";
                const bioEl = tbody.querySelector('p.ManagerP');
                const bio = bioEl ? bioEl.textContent.trim() : "无简介";
                
                let gender = "", edu = "", age = "", duty = "", date_range = "";
                tbody.querySelectorAll('td').forEach(td => {
                    const text = td.textContent.trim();
                    if (text.includes('性别:')) gender = text.replace('性别:', '').trim();
                    if (text.includes('学历:')) edu = text.replace('学历:', '').trim();
                    if (text.includes('当前年龄:')) age = text.replace('当前年龄:', '').trim();
                    if (text.includes('职务:')) duty = text.replace('职务:', '').trim();
                    if (text.includes('任职时间:')) date_range = text.replace('任职时间:', '').trim();
                });
                
                resultText += `姓名: ${name}\\n`;
                resultText += `性别: ${gender}\\n`;
                resultText += `学历: ${edu}\\n`;
                resultText += `当前年龄: ${age}\\n`;
                resultText += `职务: ${duty}\\n`;
                resultText += `任职时间: ${date_range}\\n`;
                resultText += `个人履历: ${bio}\\n`;
                resultText += `--------------------\\n`;
            });
            return resultText;
        }
    ''')
    
    if not cleaned_data.strip():
        return None

    # 核心修改：重新构建面向“高管团队整体”的评分与排查 Prompt
    final_prompt = f"""# Role
你是一个资深的投行 IPO 核心审查专家与上市公司风险控制分析师，擅长对企业核心管理层的治理结构、高管团队综合素养进行整体量化评估，并能穿透识别“家族企业/裙带关系”潜在的治理风险。

# Task
请通盘阅读 [# 核心高管原始数据]，独立且客观地完成以下两个任务：
1. 【高管团队整体量化评分】：依据 [# 团队评分标准]，对该上市公司的管理团队进行**整体百分制（100分满分）**综合评分，并给出核心扣分/加分理由。
2. 【家族企业风控排查】：将所有高管作为一个整体进行交叉比对，综合评估该公司（{company_name}）是否属于“疑似家族企业或裙带控制企业”，并给出最终的定性结论与排查证据链。

# 任务一：高管团队评分标准（满分 100 分）
请对该高管团队的**整体结构**进行统筹打分：
- 团队学历与素养结构（满分 30 分）：评估团队整体学历含金量。核心骨干高管中博士、名校MBA、硕士占比高（25-30分）；以本科为主且核心岗位有高含金量专业证书如CPA/CFA（18-24分）；学历普遍偏低（10-17分）。
- 团队年龄梯队与活力（满分 20 分）：评估新老交接与精力和经验的平衡度。新老梯队搭配合理（如50后/60后坐镇，70后/80后作为中坚执行层）（17-20分）；年龄严重断层或整体严重高龄化（10-16分）。
- 团队履历匹配度与行业声誉（满分 50 分）：评估团队的行业号召力与技术管理硬实力。多位核心高管拥有行业标杆大厂履历或研发技术核心背景，且有行业顶级荣誉（如金牌董秘）（40-50分）；跨行业背景拼凑、缺乏行业深耕经验（25-39分）。

# 任务二：疑似家族企业排查逻辑（重点）
请将所有人联系起来，从以下蛛丝马迹中穿透审查该公司是否属于疑似家族或裙带企业：
1. 姓氏与血缘关联：高管层中是否存在核心姓氏重合，或是否存在明显的“老一代创始人（55-75岁）”与“年轻一代高管（30-45岁）”在核心岗位上的代际传承嫌疑。
2. 历史履历交集：多名高管是否在“早期前身公司”（例如：苏州旭创科技、山东中际电工等）长期共事，从而形成了高度绑定的内部人控制或裙带网。
3. 外部实体交叉：重点审查高管履历中提及的外部私营实体或投资平台（例如：天庭阙企业管理、方硕电子、中际投资等）。若多名高管在同一家外部公司共同持股或交叉任职，视为高度疑似裙带/家族利益输送风险。
4. 权力集中度：董事长、总裁、法定代表人等核心权力是否高度集中于一人，且财务总监等关键风控岗位由其长期共事的心腹担任。

# Output Format
请严格按照以下 JSON 格式输出，不要包含任何 markdown 标记（如 ```json）或解释文字。

{{
  "高管团队综合评分": {{
    "团队综合总分": "数字 (0-100)",
    "得分拆解": {{
      "团队学历结构得分": "数字",
      "团队年龄梯队得分": "数字",
      "团队履历声誉得分": "数字"
    }},
    "团队整体优势": "一句话概括团队长处（如：技术高管云集，多博士高学历，合规与资本运作经验丰富）",
    "团队整体短板": "一句话概括团队潜在的短板（如：核心管理层整体年龄逼近60岁，面临代际交接棒的隐患）"
  }},
  "家族企业风控审计": {{
    "是否疑似家族企业或裙带控制": "是 / 否 / 高度疑似",
    "风险定性结论": "一句话概括该公司管理层的治理结构特征（例如：属于典型的高校技术派与历史并购团队交叉治理，而非家族企业）",
    "排查证据链": [
      "证据1：分析高管层是否存在血缘/姓氏重合或代际传承特征。",
      "证据2：列举高管在历史共事经历上的交集，评估内部人控制风险。",
      "证据3：列举高管在外部关联实体中的交叉任职与持股现象。"
    ]
  }}
}}

# 核心高管原始数据
{cleaned_data}"""

    return final_prompt


async def main():
    # 获取 A 股全部股票数据
    stock_info = ak.stock_info_a_code_name()
    stock_code_list = stock_info['code'].tolist()
    stock_name_list = stock_info['name'].tolist()


    # 扁平化数据暂存列表（单行代表一家公司）
    company_evaluations = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        page = await browser.new_page()

        # 💡 本地快速测试前 5 只股票。正式全量跑批请删掉 [:5]
        for i, code in enumerate(stock_code_list[:5]):
            if code.startswith('6'):
                code_with_prefix = f"SH{code}"
            else:
                code_with_prefix = f"SZ{code}"
            
            company_name = stock_name_list[i]
            executive_info_page = f"https://emweb.securities.eastmoney.com/pc_hsf10/pages/index.html?type=web&code={code_with_prefix}&color=b#/gsgg/glcjj"
            
            # 生成提示词
            prompt = await generate_prompt(page, executive_info_page, company_name)
            if not prompt:
                continue
            
                
            # 请求大模型
            result = call_llm_analyzer(prompt)
            if not result:
                continue

            # --- 解析并清洗大模型返回的团队层级结构化数据 ---
            team_score_info = result.get("高管团队综合评分", {})
            score_breakdown = team_score_info.get("得分拆解", {})
            risk_audit = result.get("家族企业风控审计", {})
            
            # 将多条证据链转换为一整段文本，方便放入 CSV 单元格
            evidence_chain = " | ".join(risk_audit.get("排查证据链", []))

            # 组装公司级单行记录
            company_row = {
                "公司代码": code_with_prefix,
                "公司名称": company_name,
                "团队综合总分": team_score_info.get("团队综合总分"),
                "团队学历结构得分": score_breakdown.get("团队学历结构得分"),
                "团队年龄梯队得分": score_breakdown.get("团队年龄梯队得分"),
                "团队履历声誉得分": score_breakdown.get("团队履历声誉得分"),
                "团队整体优势": team_score_info.get("团队整体优势"),
                "团队整体短板": team_score_info.get("团队整体短板"),
                "是否疑似家族企业或裙带控制": risk_audit.get("是否疑似家族企业或裙带控制"),
                "风险定性结论": risk_audit.get("风险定性结论"),
                "排查证据链汇总": evidence_chain
            }
            
            company_evaluations.append(company_row)
            print(f"✅ 已完成 {company_name} ({code_with_prefix}) 的团队综合审计。")
            # 友好获取东财数据
            time.sleep(5)

        await browser.close()

    # --- 数据持久化落地为单一公司维度的 CSV 文件 ---
    if company_evaluations:
        df_result = pd.DataFrame(company_evaluations)
        # 使用 utf-8-sig 编码防止 Excel 打开中文产生乱码
        output_filename = "company_executive_team_evaluation.csv"
        df_result.to_csv(output_filename, index=False, encoding="utf-8-sig")
        print(f"\n💾 所有公司的团队评估已成功合并保存至: {output_filename}")


if __name__ == "__main__":
    asyncio.run(main())