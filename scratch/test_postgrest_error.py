import httpx
import asyncio

async def test():
    url = "https://ajcznltdbwvhmhgzufzv.supabase.co/rest/v1/agent_onboarding_sessions?on_conflict=owner_id&select=*"
    headers = {
        "apikey": "sb_publishable_uc38EaUEzRN40zISUiwijg_pluLI3Bt",
        "Authorization": "Bearer sb_publishable_uc38EaUEzRN40zISUiwijg_pluLI3Bt",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation"
    }
    payload = {
        "owner_id": "f03ec7c0-bfce-460d-9ff2-65895c3f2a10",
        "agent_name": "42 брат"
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json=payload)
        print("Status Code:", resp.status_code)
        print("Response Body:", resp.text)

if __name__ == "__main__":
    asyncio.run(test())
