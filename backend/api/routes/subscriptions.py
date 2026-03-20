from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from backend.api.dependencies import (
    get_current_user,
    get_subscription_delivery_service,
    get_optional_current_user,
    get_subscription_service,
    get_trending_service,
)
from backend.api.feature_flags import require_feature_enabled
from backend.models.schemas import (
    MessageResponse,
    RuntimeConfigResponse,
    RuntimeConfigUpdateRequest,
    SubscriptionCreateRequest,
    SubscriptionDeleteResponse,
    SubscriptionResponse,
    SubscriptionUpdateRequest,
)
from backend.services.subscription_service import (
    DuplicateSubscriptionError,
    SubscriptionService,
)
from backend.services.subscription_delivery_service import SubscriptionDeliveryService


router = APIRouter(tags=["subscriptions"])
LOGGER = logging.getLogger(__name__)


def _model_to_payload(model) -> dict:
    payload = model.model_dump(exclude_none=True)
    if "repo_url" in payload:
        payload["repo_url"] = str(payload["repo_url"])
    return payload


def _queue_instant_delivery_if_needed(
    subscription: dict,
    delivery_service: SubscriptionDeliveryService,
) -> None:
    if str(subscription.get("delivery_mode", "")).strip().lower() != "instant":
        return
    if not str(subscription.get("recipient_email", "")).strip():
        return
    try:
        delivery_service.queue_instant_delivery(int(subscription["id"]))
    except Exception as exc:
        LOGGER.warning("failed to queue instant subscription delivery: %s", exc)


@router.get("/api/subscriptions", response_model=List[SubscriptionResponse])
def list_subscriptions(
    current_user: dict | None = Depends(get_optional_current_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
) -> List[SubscriptionResponse]:
    require_feature_enabled("subscriptions")
    user_id = int(current_user["id"]) if current_user else None
    return subscription_service.list_subscriptions(user_id=user_id)


@router.get("/api/subscriptions/runtime-config", response_model=RuntimeConfigResponse)
def get_runtime_config(
    current_user: dict = Depends(get_current_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
) -> RuntimeConfigResponse:
    require_feature_enabled("subscriptions")
    return subscription_service.get_runtime_config(user_id=int(current_user["id"]))


@router.put("/api/subscriptions/runtime-config", response_model=RuntimeConfigResponse)
def update_runtime_config(
    request: RuntimeConfigUpdateRequest,
    current_user: dict = Depends(get_current_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
) -> RuntimeConfigResponse:
    require_feature_enabled("subscriptions")
    payload = request.model_dump(exclude_unset=True)
    updated = subscription_service.update_runtime_config(user_id=int(current_user["id"]), payload=payload)
    get_trending_service.cache_clear()
    return updated


@router.delete("/api/subscriptions/runtime-config", response_model=RuntimeConfigResponse)
def clear_runtime_config(
    current_user: dict = Depends(get_current_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
) -> RuntimeConfigResponse:
    require_feature_enabled("subscriptions")
    cleared = subscription_service.clear_runtime_config(user_id=int(current_user["id"]))
    get_trending_service.cache_clear()
    return cleared


@router.post("/api/subscriptions", response_model=SubscriptionResponse)
def create_subscription(
    request: SubscriptionCreateRequest,
    current_user: dict = Depends(get_current_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
    delivery_service: SubscriptionDeliveryService = Depends(get_subscription_delivery_service),
) -> SubscriptionResponse:
    require_feature_enabled("subscriptions")
    try:
        created = subscription_service.create_subscription(
            user_id=int(current_user["id"]),
            payload=_model_to_payload(request),
        )
    except DuplicateSubscriptionError as exc:
        raise HTTPException(status_code=409, detail={"code": "DUPLICATE_SUBSCRIPTION", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "CREATE_SUBSCRIPTION_FAILED", "message": str(exc)}) from exc
    _queue_instant_delivery_if_needed(created, delivery_service)
    return created


@router.put("/api/subscriptions/{subscription_id}", response_model=SubscriptionResponse)
def update_subscription(
    subscription_id: int,
    request: SubscriptionUpdateRequest,
    current_user: dict = Depends(get_current_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
    delivery_service: SubscriptionDeliveryService = Depends(get_subscription_delivery_service),
) -> SubscriptionResponse:
    require_feature_enabled("subscriptions")
    payload = _model_to_payload(request)
    try:
        updated = subscription_service.update_subscription(
            user_id=int(current_user["id"]),
            subscription_id=subscription_id,
            payload=payload,
        )
    except DuplicateSubscriptionError as exc:
        raise HTTPException(status_code=409, detail={"code": "DUPLICATE_SUBSCRIPTION", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "UPDATE_SUBSCRIPTION_FAILED", "message": str(exc)}) from exc

    if not updated:
        raise HTTPException(
            status_code=404,
            detail={"code": "SUBSCRIPTION_NOT_FOUND", "message": f"subscription {subscription_id} not found"},
        )
    _queue_instant_delivery_if_needed(updated, delivery_service)
    return updated


@router.delete("/api/subscriptions/{subscription_id}", response_model=SubscriptionDeleteResponse)
def delete_subscription(
    subscription_id: int,
    current_user: dict = Depends(get_current_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
) -> SubscriptionDeleteResponse:
    require_feature_enabled("subscriptions")
    try:
        deleted = subscription_service.delete_subscription(
            user_id=int(current_user["id"]),
            subscription_id=subscription_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "DELETE_SUBSCRIPTION_FAILED", "message": str(exc)}) from exc

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={"code": "SUBSCRIPTION_NOT_FOUND", "message": f"subscription {subscription_id} not found"},
        )
    return {"deleted": True}


@router.post("/api/subscriptions/{subscription_id}/send", response_model=MessageResponse)
def send_subscription(
    subscription_id: int,
    current_user: dict = Depends(get_current_user),
    delivery_service: SubscriptionDeliveryService = Depends(get_subscription_delivery_service),
) -> MessageResponse:
    require_feature_enabled("subscriptions")
    try:
        delivery_service.send_subscription_now(
            subscription_id,
            owner_user_id=int(current_user["id"]),
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "SUBSCRIPTION_NOT_FOUND", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_SUBSCRIPTION_DELIVERY", "message": str(exc)},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "SUBSCRIPTION_DELIVERY_FAILED", "message": str(exc)},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "SUBSCRIPTION_DELIVERY_FAILED", "message": str(exc)},
        ) from exc
    return {"message": "subscription email sent"}
