from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, HTTPException, Request, Response, status

from src.application.common.dao.auth import AuthSessionDao
from src.application.dto import UserDto
from src.application.use_cases.auth.commands.email import (
    ChangeEmail,
    ChangeEmailDto,
    ConfirmEmailVerification,
    ConfirmEmailVerificationDto,
    RequestEmailVerification,
    RequestEmailVerificationDto,
)
from src.application.use_cases.auth.commands.login import LoginEmailUser, LoginEmailUserDto
from src.application.use_cases.auth.commands.password import (
    ChangePassword,
    ChangePasswordDto,
    ConfirmPasswordReset,
    ConfirmPasswordResetDto,
    RequestPasswordReset,
    RequestPasswordResetDto,
)
from src.application.use_cases.auth.commands.register import (
    RegisterEmailUser,
    RegisterEmailUserDto,
)
from src.application.use_cases.auth.commands.session import RefreshSession, RefreshSessionDto
from src.application.use_cases.auth.commands.telegram import (
    AuthenticateTelegram,
    AuthenticateTelegramWebApp,
    LinkTelegram,
    LinkTelegramData,
    TelegramAuthData,
)
from src.core.config import AppConfig
from src.core.exceptions import EmailDeliveryDisabledError, EmailDeliveryError
from src.web.schemas import (
    AuthResponse,
    ChangeEmailRequest,
    ChangeEmailResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    ConfirmEmailVerificationRequest,
    ConfirmEmailVerificationResponse,
    ConfirmPasswordResetRequest,
    LoginRequest,
    LogoutResponse,
    MeResponse,
    PasswordResetResponse,
    RegisterRequest,
    RequestEmailVerificationCodeRequest,
    RequestEmailVerificationCodeResponse,
    RequestPasswordResetRequest,
    TelegramAuthRequest,
    TelegramWebAppAuthRequest,
)

from ._common import (
    CurrentUser,
    clear_auth_cookies,
    issue_session,
    set_auth_cookies,
)

router = APIRouter(prefix="/auth", tags=["Public - Auth"])


def _to_me_response(user: UserDto) -> MeResponse:
    return MeResponse(
        telegram_id=user.telegram_id,
        auth_type=user.auth_type,
        email=user.email,
        is_email_verified=user.is_email_verified,
        pending_email=user.pending_email,
        name=user.name,
        username=user.username,
        language=user.language.value,
    )


async def _issue_and_set(
    user: UserDto,
    response: Response,
    config: AppConfig,
    auth_session: AuthSessionDao,
) -> AuthResponse:
    access_token, refresh_token, auth_response = await issue_session(user, config, auth_session)
    set_auth_cookies(response, access_token, refresh_token)
    return auth_response


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
@inject
async def register_public_user(
    body: RegisterRequest,
    response: Response,
    config: FromDishka[AppConfig],
    register_email_user: FromDishka[RegisterEmailUser],
    auth_session: FromDishka[AuthSessionDao],
) -> AuthResponse:
    user = await register_email_user.system(
        RegisterEmailUserDto(
            email=body.email,
            password=body.password,
            name=body.name,
            referral_code=body.referral_code,
        )
    )
    return await _issue_and_set(user, response, config, auth_session)


@router.post("/login", response_model=AuthResponse)
@inject
async def login_public_user(
    body: LoginRequest,
    response: Response,
    config: FromDishka[AppConfig],
    login_email_user: FromDishka[LoginEmailUser],
    auth_session: FromDishka[AuthSessionDao],
) -> AuthResponse:
    user = await login_email_user.system(
        LoginEmailUserDto(email=body.email, password=body.password)
    )
    return await _issue_and_set(user, response, config, auth_session)


@router.post("/refresh", response_model=AuthResponse)
@inject
async def refresh_access_token(
    request: Request,
    response: Response,
    config: FromDishka[AppConfig],
    refresh_session: FromDishka[RefreshSession],
    auth_session: FromDishka[AuthSessionDao],
) -> AuthResponse:
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")
    user = await refresh_session.system(RefreshSessionDto(refresh_token=refresh_token))
    return await _issue_and_set(user, response, config, auth_session)


@router.post("/logout", response_model=LogoutResponse)
@inject
async def logout(
    request: Request,
    response: Response,
    user: CurrentUser,
    auth_session: FromDishka[AuthSessionDao],
) -> LogoutResponse:
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        await auth_session.revoke_refresh_token(refresh_token)
    clear_auth_cookies(response)
    return LogoutResponse(success=True)


@router.post("/telegram", response_model=AuthResponse)
@inject
async def telegram_login(
    body: TelegramAuthRequest,
    response: Response,
    config: FromDishka[AppConfig],
    authenticate_telegram: FromDishka[AuthenticateTelegram],
    auth_session: FromDishka[AuthSessionDao],
) -> AuthResponse:
    user = await authenticate_telegram.system(
        TelegramAuthData(
            id=body.id,
            first_name=body.first_name,
            last_name=body.last_name,
            username=body.username,
            payload=body.model_dump(exclude_none=True),
        )
    )
    return await _issue_and_set(user, response, config, auth_session)


@router.post("/telegram/webapp", response_model=AuthResponse)
@inject
async def telegram_webapp_login(
    body: TelegramWebAppAuthRequest,
    response: Response,
    config: FromDishka[AppConfig],
    authenticate_webapp: FromDishka[AuthenticateTelegramWebApp],
    auth_session: FromDishka[AuthSessionDao],
) -> AuthResponse:
    user = await authenticate_webapp.system(body.init_data)
    return await _issue_and_set(user, response, config, auth_session)


@router.post("/telegram/link", response_model=MeResponse)
@inject
async def link_telegram_account(
    body: TelegramAuthRequest,
    user: CurrentUser,
    link_telegram: FromDishka[LinkTelegram],
) -> MeResponse:
    updated = await link_telegram(
        user,
        LinkTelegramData(
            id=body.id,
            username=body.username,
            payload=body.model_dump(exclude_none=True),
        ),
    )
    return _to_me_response(updated)


@router.get("/me", response_model=MeResponse)
@inject
async def get_public_user_profile(user: CurrentUser) -> MeResponse:
    return _to_me_response(user)


@router.post("/change-password", response_model=ChangePasswordResponse)
@inject
async def change_public_user_password(
    body: ChangePasswordRequest,
    response: Response,
    user: CurrentUser,
    config: FromDishka[AppConfig],
    change_password: FromDishka[ChangePassword],
    auth_session: FromDishka[AuthSessionDao],
) -> ChangePasswordResponse:
    updated = await change_password(
        user,
        ChangePasswordDto(current_password=body.current_password, new_password=body.new_password),
    )
    # All sessions were revoked; rotate the current device into a fresh session.
    await _issue_and_set(updated, response, config, auth_session)
    return ChangePasswordResponse(success=True)


@router.post("/password/request-reset", response_model=PasswordResetResponse)
@inject
async def request_password_reset(
    body: RequestPasswordResetRequest,
    request_password_reset_uc: FromDishka[RequestPasswordReset],
) -> PasswordResetResponse:
    await request_password_reset_uc.system(RequestPasswordResetDto(email=body.email))
    return PasswordResetResponse(success=True)


@router.post("/password/confirm-reset", response_model=PasswordResetResponse)
@inject
async def confirm_password_reset(
    body: ConfirmPasswordResetRequest,
    response: Response,
    confirm_password_reset_uc: FromDishka[ConfirmPasswordReset],
) -> PasswordResetResponse:
    await confirm_password_reset_uc.system(
        ConfirmPasswordResetDto(
            email=body.email,
            code=body.code,
            new_password=body.new_password,
        )
    )
    clear_auth_cookies(response)
    return PasswordResetResponse(success=True)


@router.post("/email/change", response_model=ChangeEmailResponse)
@inject
async def change_email(
    body: ChangeEmailRequest,
    user: CurrentUser,
    change_email_uc: FromDishka[ChangeEmail],
) -> ChangeEmailResponse:
    await change_email_uc(user, ChangeEmailDto(email=body.email))
    return ChangeEmailResponse(success=True, pending_email=body.email)


@router.post("/email/request-verification", response_model=RequestEmailVerificationCodeResponse)
@inject
async def request_email_verification_code(
    body: RequestEmailVerificationCodeRequest,
    user: CurrentUser,
    request_verification: FromDishka[RequestEmailVerification],
) -> RequestEmailVerificationCodeResponse:
    try:
        result = await request_verification(user, RequestEmailVerificationDto(email=body.email))
    except EmailDeliveryDisabledError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e
    except EmailDeliveryError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    return RequestEmailVerificationCodeResponse(
        success=True, target_email=result.target_email, expires_at=result.expires_at
    )


@router.post("/email/confirm", response_model=ConfirmEmailVerificationResponse)
@inject
async def confirm_email_verification(
    body: ConfirmEmailVerificationRequest,
    user: CurrentUser,
    confirm_verification: FromDishka[ConfirmEmailVerification],
) -> ConfirmEmailVerificationResponse:
    result = await confirm_verification(user, ConfirmEmailVerificationDto(code=body.code))
    return ConfirmEmailVerificationResponse(success=True, email=result.email)
