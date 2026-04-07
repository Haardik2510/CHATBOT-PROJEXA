"""Backend persistence layer with Supabase primary support and Mongo fallback."""
import asyncio
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase_client import get_supabase_admin_client, has_supabase_config


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AppStore:
    """Provide a single async API for app persistence."""

    def __init__(self, mongo_db=None):
        self.mongo_db = mongo_db
        self.supabase = get_supabase_admin_client() if has_supabase_config() else None
        self.use_supabase = bool(self.supabase)

    async def _run_supabase(self, fn):
        return await asyncio.to_thread(fn)

    async def ping(self):
        if self.use_supabase:
            await self._run_supabase(
                lambda: self.supabase.table("profiles").select("id").limit(1).execute()
            )
            return

        if self.mongo_db is None:
            raise RuntimeError("No database backend configured")
        await self.mongo_db.command("ping")

    def backend_name(self) -> str:
        return "supabase" if self.use_supabase else "mongo"

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        if self.use_supabase:
            response = await self._run_supabase(
                lambda: self.supabase.table("profiles").select("*").eq("id", user_id).limit(1).execute()
            )
            return response.data[0] if response.data else None

        return await self.mongo_db.users.find_one({"id": user_id}, {"_id": 0})

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        if self.use_supabase:
            response = await self._run_supabase(
                lambda: self.supabase.table("profiles").select("*").eq("email", email).limit(1).execute()
            )
            return response.data[0] if response.data else None

        return await self.mongo_db.users.find_one({"email": email}, {"_id": 0})

    async def get_user_by_clerk_user_id(self, clerk_user_id: str) -> Optional[Dict[str, Any]]:
        if self.use_supabase:
            response = await self._run_supabase(
                lambda: self.supabase.table("profiles").select("*").eq("clerk_user_id", clerk_user_id).limit(1).execute()
            )
            return response.data[0] if response.data else None

        return await self.mongo_db.users.find_one({"clerk_user_id": clerk_user_id}, {"_id": 0})

    async def save_user(self, record: Dict[str, Any]) -> Dict[str, Any]:
        payload = {**record}
        payload.setdefault("updated_at", utc_now_iso())

        if self.use_supabase:
            allowed_keys = {
                "id",
                "email",
                "name",
                "role",
                "picture",
                "clerk_user_id",
                "auth_provider",
                "is_active",
                "created_at",
                "updated_at",
            }
            payload = {key: value for key, value in payload.items() if key in allowed_keys}
            await self._run_supabase(
                lambda: self.supabase.table("profiles").upsert(payload, on_conflict="id").execute()
            )
            return await self.get_user_by_id(payload["id"])

        if await self.mongo_db.users.find_one({"id": payload["id"]}, {"_id": 1}):
            await self.mongo_db.users.update_one({"id": payload["id"]}, {"$set": payload})
        else:
            await self.mongo_db.users.insert_one(payload)
        return await self.get_user_by_id(payload["id"])

    async def list_users(self, limit: int = 100) -> List[Dict[str, Any]]:
        if self.use_supabase:
            response = await self._run_supabase(
                lambda: self.supabase.table("profiles").select("*").order("created_at", desc=True).limit(limit).execute()
            )
            return response.data or []

        return await self.mongo_db.users.find({}, {"_id": 0, "password_hash": 0}).to_list(limit)

    async def count_users(self) -> int:
        if self.use_supabase:
            response = await self._run_supabase(
                lambda: self.supabase.table("profiles").select("id", count="exact").limit(1).execute()
            )
            if getattr(response, "count", None) is not None:
                return int(response.count)
            return len(response.data or [])

        return await self.mongo_db.users.count_documents({})

    async def update_user_role(self, user_id: str, role: str) -> bool:
        if self.use_supabase:
            response = await self._run_supabase(
                lambda: self.supabase.table("profiles").update(
                    {"role": role, "updated_at": utc_now_iso()}
                ).eq("id", user_id).execute()
            )
            return bool(response.data)

        result = await self.mongo_db.users.update_one({"id": user_id}, {"$set": {"role": role}})
        return result.modified_count > 0

    async def delete_user(self, user_id: str) -> bool:
        if self.use_supabase:
            response = await self._run_supabase(
                lambda: self.supabase.table("profiles").delete().eq("id", user_id).execute()
            )
            return bool(response.data)

        result = await self.mongo_db.users.delete_one({"id": user_id})
        if result.deleted_count:
            await self.mongo_db.chat_sessions.delete_many({"user_id": user_id})
            return True
        return False

    async def create_document(self, record: Dict[str, Any]) -> Dict[str, Any]:
        if self.use_supabase:
            allowed_keys = {
                "id",
                "title",
                "description",
                "doc_type",
                "filename",
                "storage_bucket",
                "storage_path",
                "file_size",
                "chunk_count",
                "status",
                "uploaded_by",
                "created_at",
                "indexed_at",
                "error_message",
                "is_seed",
                "category",
                "source_url",
                "verified_on",
                "total_parts",
                "processing_metadata",
            }
            payload = {key: value for key, value in record.items() if key in allowed_keys}
            await self._run_supabase(lambda: self.supabase.table("documents").insert(payload).execute())
            return await self.get_document(record["id"])

        await self.mongo_db.documents.insert_one(record)
        return record

    async def update_document(self, document_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        payload = {**fields}
        if self.use_supabase:
            allowed_keys = {
                "title",
                "description",
                "doc_type",
                "filename",
                "storage_bucket",
                "storage_path",
                "file_size",
                "chunk_count",
                "status",
                "uploaded_by",
                "created_at",
                "indexed_at",
                "error_message",
                "is_seed",
                "category",
                "source_url",
                "verified_on",
                "total_parts",
                "processing_metadata",
            }
            payload = {key: value for key, value in payload.items() if key in allowed_keys}
            response = await self._run_supabase(
                lambda: self.supabase.table("documents").update(payload).eq("id", document_id).execute()
            )
            if response.data:
                return response.data[0]
            return await self.get_document(document_id)

        await self.mongo_db.documents.update_one({"id": document_id}, {"$set": payload})
        return await self.get_document(document_id)

    async def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        if self.use_supabase:
            response = await self._run_supabase(
                lambda: self.supabase.table("documents").select("*").eq("id", document_id).limit(1).execute()
            )
            return response.data[0] if response.data else None

        return await self.mongo_db.documents.find_one({"id": document_id}, {"_id": 0})

    async def list_documents(self, limit: int = 100) -> List[Dict[str, Any]]:
        if self.use_supabase:
            response = await self._run_supabase(
                lambda: self.supabase.table("documents").select("*").order("created_at", desc=True).limit(limit).execute()
            )
            return response.data or []

        return await self.mongo_db.documents.find({}, {"_id": 0}).sort("created_at", -1).to_list(limit)

    async def count_documents(self, filters: Optional[Dict[str, Any]] = None) -> int:
        filters = filters or {}
        if self.use_supabase:
            query = self.supabase.table("documents").select("id", count="exact")
            for key, value in filters.items():
                query = query.eq(key, value)
            response = await self._run_supabase(lambda: query.limit(1).execute())
            if getattr(response, "count", None) is not None:
                return int(response.count)
            return len(response.data or [])

        return await self.mongo_db.documents.count_documents(filters)

    async def get_seed_categories(self) -> Dict[str, int]:
        if self.use_supabase:
            response = await self._run_supabase(
                lambda: self.supabase.table("documents").select("category").eq("is_seed", True).execute()
            )
            counts = Counter(item.get("category") for item in (response.data or []) if item.get("category"))
            return dict(counts)

        pipeline = [
            {"$match": {"is_seed": True}},
            {"$group": {"_id": "$category", "count": {"$sum": 1}}},
        ]
        categories = await self.mongo_db.documents.aggregate(pipeline).to_list(20)
        return {cat["_id"]: cat["count"] for cat in categories if cat["_id"]}

    async def delete_document(self, document_id: str) -> bool:
        if self.use_supabase:
            response = await self._run_supabase(
                lambda: self.supabase.table("documents").delete().eq("id", document_id).execute()
            )
            return bool(response.data)

        result = await self.mongo_db.documents.delete_one({"id": document_id})
        return result.deleted_count > 0

    async def create_chat_session(self, record: Dict[str, Any]) -> Dict[str, Any]:
        if self.use_supabase:
            allowed_keys = {"id", "user_id", "created_at", "updated_at"}
            payload = {key: value for key, value in record.items() if key in allowed_keys}
            await self._run_supabase(lambda: self.supabase.table("chat_sessions").insert(payload).execute())
            return await self.get_chat_session(record["id"], record["user_id"])

        await self.mongo_db.chat_sessions.insert_one(record)
        return record

    async def append_chat_turn(
        self,
        session_id: str,
        message: str,
        response_text: str,
        is_web_fallback: bool,
    ) -> None:
        timestamp = utc_now_iso()
        if self.use_supabase:
            await self._run_supabase(
                lambda: self.supabase.table("chat_messages").insert(
                    [
                        {"session_id": session_id, "role": "user", "content": message, "created_at": timestamp},
                        {"session_id": session_id, "role": "assistant", "content": response_text, "created_at": timestamp},
                    ]
                ).execute()
            )
            await self._run_supabase(
                lambda: self.supabase.table("chat_sessions").update({"updated_at": timestamp}).eq("id", session_id).execute()
            )
            return

        await self.mongo_db.chat_sessions.update_one(
            {"id": session_id},
            {
                "$push": {
                    "messages": {
                        "$each": [
                            {"role": "user", "content": message, "timestamp": timestamp},
                            {
                                "role": "assistant",
                                "content": response_text,
                                "timestamp": timestamp,
                                "is_web_fallback": is_web_fallback,
                            },
                        ]
                    }
                },
                "$set": {"updated_at": timestamp},
            },
        )

    async def list_chat_sessions(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        if self.use_supabase:
            response = await self._run_supabase(
                lambda: self.supabase.table("chat_sessions").select("*").eq("user_id", user_id).order("updated_at", desc=True).limit(limit).execute()
            )
            sessions = response.data or []
            for session in sessions:
                session["messages"] = await self._get_session_messages(session["id"])
            return sessions

        return await self.mongo_db.chat_sessions.find({"user_id": user_id}, {"_id": 0}).sort("updated_at", -1).to_list(limit)

    async def _get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        if self.use_supabase:
            response = await self._run_supabase(
                lambda: self.supabase.table("chat_messages").select("*").eq("session_id", session_id).order("created_at").execute()
            )
            return [
                {
                    "role": row["role"],
                    "content": row["content"],
                    "timestamp": row["created_at"],
                }
                for row in (response.data or [])
            ]

        session = await self.mongo_db.chat_sessions.find_one({"id": session_id}, {"_id": 0, "messages": 1})
        return session.get("messages", []) if session else []

    async def get_chat_session(self, session_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        if self.use_supabase:
            response = await self._run_supabase(
                lambda: self.supabase.table("chat_sessions").select("*").eq("id", session_id).eq("user_id", user_id).limit(1).execute()
            )
            if not response.data:
                return None
            session = response.data[0]
            session["messages"] = await self._get_session_messages(session_id)
            return session

        return await self.mongo_db.chat_sessions.find_one({"id": session_id, "user_id": user_id}, {"_id": 0})

    async def create_query_log(self, record: Dict[str, Any]) -> None:
        if self.use_supabase:
            allowed_keys = {
                "id",
                "user_id",
                "query",
                "response_length",
                "sources_count",
                "voice_input",
                "processing_time_ms",
                "created_at",
            }
            payload = {key: value for key, value in record.items() if key in allowed_keys}
            await self._run_supabase(lambda: self.supabase.table("query_logs").insert(payload).execute())
            return

        await self.mongo_db.query_logs.insert_one(record)

    async def list_query_logs(self, start_iso: Optional[str] = None, end_iso: Optional[str] = None) -> List[Dict[str, Any]]:
        if self.use_supabase:
            query = self.supabase.table("query_logs").select("*")
            if start_iso:
                query = query.gte("created_at", start_iso)
            if end_iso:
                query = query.lt("created_at", end_iso)
            response = await self._run_supabase(lambda: query.execute())
            return response.data or []

        filters: Dict[str, Any] = {}
        if start_iso or end_iso:
            filters["created_at"] = {}
            if start_iso:
                filters["created_at"]["$gte"] = start_iso
            if end_iso:
                filters["created_at"]["$lt"] = end_iso
        return await self.mongo_db.query_logs.find(filters, {"_id": 0}).to_list(5000)
