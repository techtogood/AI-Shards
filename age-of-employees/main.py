import os
import asyncio
import csv 
from pathlib import Path
from playwright.async_api import async_playwright
import akshare as ak  
from google import genai
from google.genai import types

def get_gemini_client():
    """安全初始化 Gemini 客户端，兼顾环境变量与硬编码兜底"""
    # 优先尝试从环境变量读取
    api_key = os.environ.get("GEMINI_API_KEY")
    
    # 兜底方案
    if not api_key or api_key == "YOUR_GEMINI_API_KEY":
        api_key = "your_gemini_api_key"  
        
    if not api_key or len(api_key) < 15:
        raise ValueError("❌ 错误：未检测到有效的 GEMINI_API_KEY，请检查设置。")
        
    return genai.Client(api_key=api_key)

async def analyze_pdf_with_gemini(client: genai.Client, file_path: Path) -> str:
    """使用全新 google-genai SDK 上传并分析长文档"""
    print(f"🚀 开始将文件上传至全新 Gemini File API: {file_path.name}...")
    
    uploaded_file = None
    try:
        with open(file_path, "rb") as f:
            uploaded_file = client.files.upload(
                file=f,
                config=types.UploadFileConfig(
                    mime_type="application/pdf",
                    display_name="target_prospectus.pdf"
                )
            )
        print(f"✅ 文件上传成功，远程名称: {uploaded_file.name}")
        
        prompt = """
        你是一个资深的投行分析师和数据挖掘专家。请仔细阅读这份招股说明书，并完成以下任务：
        1. 找到书中关于“员工”、“人员构成”、“员工年龄”或“社会保障”的相关章节。
        2. 提取出书中披露的员工总数以及各年龄段（如30岁以下、30-40岁、40岁以上等）的员工人数或比例。
        3. 依据披露的具体数据或各年龄段的中位数，精细估算出该企业员工的【平均年龄】。
        4. 给出你的估算逻辑和推导过程，并标明数据出处（如：招股书第XX页）。如果书中直接披露了平均年龄，请直接指出。
        
        请用清晰的结构化中文回答。
        """
        
        print("🤖 正在等待 Gemini 深度解析长文档，请稍候...")
        response = client.models.generate_content(
            model='gemini-flash-lite-latest',  
            contents=[uploaded_file, prompt]
        )
        return response.text

    except Exception as e:
        return f"Gemini 新版 SDK 调用或分析失败: {e}"
        
    finally:
        if uploaded_file:
            try:
                print("🧹 正在清理 Gemini 服务器上的临时文件...")
                client.files.delete(name=uploaded_file.name)
            except Exception as delete_error:
                print(f"⚠️ 清理云端文件时发生轻微异常: {delete_error}")


async def main_workflow():
    try:
        client = get_gemini_client()
    except ValueError as e:
        print(e)
        return
    
    # 获取 A 股全部股票数据
    print("正在获取全 A 股数据并过滤上交所...")
    try:
        # 获取全 A 股代码和名称
        all_stock_df = ak.stock_info_a_code_name()
        
        # 过滤出所有以 "6" 开头的上交所股票代码
        sh_code_list = [
            code for code in all_stock_df['code'].tolist() 
            if code.startswith('6')
        ]
        
        print(f"✅ 过滤完成，上交所（主板+科创板）共有: {len(sh_code_list)} 只股票")
        print("后 10 只股票代码示例:", sh_code_list[-10:])

    except Exception as e:
        print(f"❌ 获取数据失败: {e}")

    async with async_playwright() as p:
        print("正在启动浏览器...")
        browser = await p.chromium.launch(headless=True, channel="chrome")
        
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        download_dir = Path("./downloads")
        download_dir.mkdir(exist_ok=True)

        # 💡 追加逻辑：初始化 CSV 文件并写入表头
        csv_file_path = Path("analysis_results.csv")
        with open(csv_file_path, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["股票代码", "文件名称", "分析结果"])

        # 批量循环
        #测试最后5个
        #for code in sh_code_list[-5:]: 
        #全量运行
        for code in sh_code_list:
            target_url = f"https://www.sse.com.cn/ipo/bookbuilding/detail/index.shtml?securityCode={code}" 
            print(f"\n🔍 正在检索股票代码: {code} | 网址: {target_url}")
        
            try:
                await page.goto(target_url, wait_until="networkidle", timeout=15000)
                
                target_links_locator = page.locator('.js-detail-table table tbody a', has_text="招股说明书")
                count = await target_links_locator.count()
                
                if count == 0:
                    print(f"ℹ️ 股票 {code} 未找到招股说明书相关链接，跳过。")
                    continue  # 💡 修正：使用 continue 而不是 return，防止终止大循环

                for i in range(count):
                    link_element = target_links_locator.nth(i)
                    link_text = await link_element.inner_text()

                    
                    if "摘要"  in link_text or "提示性公告" in link_text:
                        print(f"ℹ️ 股票 {code} 找到摘要或提示性公告相关链接，跳过。")
                        continue
                    
                    print(f"================ 正在处理: {link_text} ================")
                    await link_element.scroll_into_view_if_needed()
                    
                    async with context.expect_page() as new_page_info:
                        await link_element.click()
                    
                    pdf_page = await new_page_info.value
                    await pdf_page.wait_for_load_state("networkidle")
                    await pdf_page.wait_for_timeout(2000)
                    
                    pdf_url = pdf_page.url
                    response = await pdf_page.request.get(pdf_url)
                    
                    if response.status == 200:
                        safe_filename = f"{link_text.replace('/', '_').strip()}.pdf"
                        save_path = download_dir / safe_filename
                        
                        save_path.write_bytes(await response.body())
                        print(f"✅ 1. 本地下载完成: {save_path.resolve()}")
                        
                        await pdf_page.close()
                        
                        # 执行新版 SDK 分析逻辑
                        ai_result = await analyze_pdf_with_gemini(client, save_path)
                        print(f"\n📊 【Gemini 分析结果】:\n{ai_result}")
                        print("========================================================\n")
                        
                        # 💡 追加逻辑：将单条分析结果实时追加写入 CSV 文件
                        with open(csv_file_path, mode="a", newline="", encoding="utf-8-sig") as f:
                            writer = csv.writer(f)
                            writer.writerow([code, link_text, ai_result])
                        print(f"💾 结果已同步保存至 CSV 缓存。")
                        
                    else:
                        print(f"❌ 获取 PDF 内容失败，状态码: {response.status}")
                        await pdf_page.close()
                    
                    await page.wait_for_timeout(1000)

            except Exception as e:
                print(f"⚠️ 处理股票 {code} 时发生未知错误: {e}")
                # 即使单只股票的内部逻辑报错，也继续下一只
                continue
            
            # 💡 原来的 finally 块被移除，不再在这个位置执行 browser.close()
            await page.wait_for_timeout(1000)

        # 💡 核心修改：当所有股票代码都遍历完成后，再统一关闭浏览器
        print("🎉 所有批量队列处理完毕，正在注销组件...")
        await context.close()
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main_workflow())