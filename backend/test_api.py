import requests
import json

url = "http://localhost:8000/api/v1/check"
payload = {
    "claim": "伊朗总统哈梅内伊死了没有",
    "enable_thinking": True,
    "enable_link_validation": False,
    "enable_consistency_check": False
}

print("发送信息核查请求...")
print(f"查询: {payload['claim']}")
print("=" * 60)

try:
    response = requests.post(url, json=payload, timeout=120)
    
    if response.status_code == 200:
        result = response.json()
        
        print("\n✅ 核查完成！\n")
        print(f"【核查结论】{result['verdict']}")
        print(f"\n【关键证据】")
        print(result['evidence_quote'][:200] if len(result['evidence_quote']) > 200 else result['evidence_quote'])
        print(f"\n【证据来源】")
        print(result['source_url'] if result['source_url'] else '无')
        print(f"\n【不确定性说明】")
        print(result['uncertainty_note'])
        print(f"\n【推理过程】")
        reasoning = result.get('reasoning', '')
        if reasoning:
            print(reasoning[:500] + "..." if len(reasoning) > 500 else reasoning)
        else:
            print("无")
            
        if result.get('thinking_process'):
            print(f"\n【深度思考过程】")
            print(result['thinking_process'][:300] + "..." if len(result['thinking_process']) > 300 else result['thinking_process'])
    else:
        print(f"❌ 请求失败: {response.status_code}")
        print(response.text)
        
except Exception as e:
    print(f"❌ 测试失败: {e}")

print("\n" + "=" * 60)
