import requests
import json

# 测试信息核查API
url = "http://localhost:8000/api/v1/check"
payload = {
    "claim": "伊朗总统哈梅内伊死了没有",
    "enable_thinking": True
}

print("=" * 60)
print("测试GLM-5完整输出")
print("=" * 60)

response = requests.post(url, json=payload, timeout=120)

if response.status_code == 200:
    result = response.json()
    
    print(f"\n【核查结论】\n{result['verdict']}")
    
    print(f"\n【关键证据】\n{result['evidence_quote']}")
    
    print(f"\n【证据来源】\n{result['source_url']}")
    
    print(f"\n【搜索关键词】\n{result['search_keywords']}")
    
    print(f"\n【不确定性说明】\n{result['uncertainty_note']}")
    
    print(f"\n【推理过程】（完整）")
    print("=" * 60)
    reasoning = result.get('reasoning', '')
    if reasoning:
        print(reasoning)
    else:
        print("无")
    
    print("\n" + "=" * 60)
    print(f"\n【深度思考过程】（完整）")
    print("=" * 60)
    thinking = result.get('thinking_process', '')
    if thinking:
        print(thinking)
    else:
        print("无")
        
    print("\n" + "=" * 60)
    print(f"\n【原始响应JSON】")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
else:
    print(f"请求失败: {response.status_code}")
    print(response.text)
