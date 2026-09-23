"""原有设置和资源管理的开发预览通信适配。"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import JsonValue
from starlette.datastructures import UploadFile

from webapp.auth.dependencies import current_user
from webapp.ui_store import UiStore

router = APIRouter()
MAX_UPLOAD_BYTES = 64 * 1024 * 1024


def get_store(request: Request, mirror_id: str = 'preview') -> UiStore:
    """取得当前浏览器的预览资源存储，路径参数不能选择其他用户。

    Args:
        request: 已由预览中间件标识浏览器的请求。
        mirror_id: 兼容原 UI 的资源命名空间，接受当前 UID 或兼容别名 preview。

    Returns:
        当前浏览器自己的资源存储。

    Raises:
        HTTPException: 请求其他命名空间时返回 403。
    """
    user = current_user(request)
    if mirror_id not in ('preview', user.uid):
        raise HTTPException(403, '无权访问其他用户的数据')
    return UiStore(request.app.state.settings.ui_data_dir / user.scope)


def file_response(store: UiStore, relative: str) -> FileResponse:
    """读取当前浏览器的资源文件。

    Args:
        store: 已完成浏览器隔离的预览存储。
        relative: 资源相对路径。

    Returns:
        存在的资源文件响应。

    Raises:
        HTTPException: 文件缺失时返回 404。
        ValueError: 路径越界时抛出，由应用统一返回 400。
    """
    target = store.path(relative)
    if not target.is_file():
        raise HTTPException(404, '资源不存在')
    return FileResponse(target)


async def save_upload(store: UiStore, relative: str, upload: UploadFile) -> None:
    """保存有大小上限的完整上传，不在服务端解压或执行内容。

    Args:
        store: 当前浏览器的资源存储。
        relative: 目标资源相对路径。
        upload: multipart 解析得到的文件。

    Raises:
        HTTPException: 文件超过限制时返回 413。
        OSError: 文件保存失败时抛出。
    """
    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, '单个资源不能超过 64 MiB')
    store.write_bytes(relative, data)


@router.api_route('/api/login-config', methods=['GET', 'PUT'])
async def login_config(request: Request) -> JsonValue:
    """保留原登录外观定制，在当前浏览器预览范围内保存。

    Args:
        request: 读取或写入登录页外观的请求。

    Returns:
        外观配置或保存成功状态，不创建登录账号。
    """
    store = get_store(request)
    if request.method == 'PUT':
        store.write_json('appearance/login.json', await request.json())
        return {'ok': True}
    return store.read_json('appearance/login.json') or {
        'loginPageTitle': '汐伴 · Tidebound', 'loginPageSubTitle': 'GalGame Web Chat',
    }


@router.api_route('/api/login-bg', methods=['GET', 'POST', 'DELETE'], response_model=None)
async def login_background(request: Request) -> JsonValue | FileResponse:
    """保留登录背景上传和清除，隔离于当前浏览器。

    Args:
        request: 上传文件、读取或删除背景的请求。

    Returns:
        背景文件或操作状态。

    Raises:
        HTTPException: 文件不存在、缺少上传或文件过大。
    """
    store = get_store(request)
    relative = 'appearance/login-bg.png'
    if request.method == 'GET':
        return file_response(store, relative)
    if request.method == 'DELETE':
        store.delete(relative)
        return {'ok': True}
    form = await request.form()
    upload = form.get('file')
    if not isinstance(upload, UploadFile):
        raise HTTPException(422, '缺少背景图片')
    await save_upload(store, relative, upload)
    return {'ok': True}


@router.api_route('/api/userdata/{mirror_id}/{resource:path}', methods=['GET', 'PUT', 'POST', 'DELETE'], response_model=None)
async def userdata(request: Request, mirror_id: str, resource: str) -> JsonValue | FileResponse:
    """适配原设置组件的配置、媒体、模型和插件数据接口。

    Args:
        request: 原 UI 发送的请求；写入只发生于本浏览器的开发预览目录。
        mirror_id: 原组件资源命名空间，必须为当前 UID 或 preview。
        resource: core、batch、媒体或插件资源相对路由。

    Returns:
        原 UI 所需的 JSON 或文件响应，不调用任何对话或模型业务。

    Raises:
        HTTPException: 不支持的接口、缺失资源、非法上传或访问其他命名空间。
        ValueError: 路径越界或请求数据非法。
    """
    store = get_store(request, mirror_id)
    store.path(resource)  # 在分支处理前统一拒绝路径穿越。
    method = request.method
    parts = resource.split('/')
    group = parts[0]
    if group == 'all' and method == 'DELETE':
        for directory in ('core', 'bgm', 'bg_images', 'models', 'mods', 'plugins', 'app_image', 'appearance'):
            store.delete(directory)
        return {'ok': True}
    if group == 'batch' and method == 'GET':
        keys = request.query_params.get('keys', '').split(',')
        result = {key: store.read_json(f'core/{key}.json') for key in keys if key}
        if request.query_params.get('media') == 'true':
            for media in ('bgm', 'bg_images', 'models', 'mods'):
                result['_' + media] = store.list_json(f'{media}/manifests')
        return result
    if group == 'core' and len(parts) == 2:
        path = f'core/{parts[1]}.json'
        if method == 'GET':
            return store.read_json(path)
        if method == 'PUT':
            store.write_json(path, await request.json())
            return {'ok': True}
        if method == 'DELETE':
            store.delete(path)
            return {'ok': True}
    if group == 'app_image' and len(parts) == 2:
        path = f'app_image/{parts[1]}'
        if method == 'GET':
            return file_response(store, path)
        if method == 'DELETE':
            store.delete(path)
            return {'ok': True}
        if method == 'POST':
            form = await request.form()
            upload = form.get('file')
            if not isinstance(upload, UploadFile):
                raise HTTPException(422, '缺少图片文件')
            await save_upload(store, path, upload)
            return {'ok': True}
    if group in ('bgm', 'bg_images', 'models', 'mods'):
        return await media_resource(request, store, parts)
    if group == 'plugins':
        return await plugin_resource(request, store, parts)
    raise HTTPException(501, '该设置后台操作尚未接入')


async def media_resource(request: Request, store: UiStore, parts: list[str]) -> JsonValue | FileResponse:
    """处理原媒体与模型控件的通信协议。

    Args:
        request: 当前资源请求及上传文件。
        store: 已隔离到本浏览器的资源存储。
        parts: 已完成路径检查的路由分段。

    Returns:
        资源 JSON、操作状态或文件响应。

    Raises:
        HTTPException: 路由不支持、文件不存在或上传不合法。
    """
    method, group = request.method, parts[0]
    if group in ('bgm', 'bg_images', 'models', 'mods'):
        if len(parts) == 1 and method == 'GET':
            return store.list_json(f'{group}/manifests')
        if len(parts) == 2 and method == 'GET':
            value = store.read_json(f'{group}/manifests/{parts[1]}.json')
            if value is None:
                raise HTTPException(404, '条目不存在')
            return value
        if len(parts) == 2 and method == 'DELETE':
            store.delete(f'{group}/manifests/{parts[1]}.json')
            store.delete(f'{group}/files/{parts[1]}')
            return {'ok': True}
        if group == 'mods' and len(parts) == 2 and method == 'PUT':
            store.write_json(f'mods/manifests/{parts[1]}.json', await request.json())
            return {'ok': True}
        if len(parts) >= 3 and method == 'GET' and parts[2] in ('file', 'files'):
            suffix = '/'.join(parts[3:]) if parts[2] == 'files' else 'content'
            return file_response(store, f'{group}/files/{parts[1]}/{suffix}')
        if len(parts) == 1 and method == 'POST' and group != 'mods':
            form = await request.form(max_files=2000, max_part_size=MAX_UPLOAD_BYTES)
            item_id, name = str(form.get('id', '')), str(form.get('name', ''))
            if not item_id or not name or '/' in item_id:
                raise HTTPException(422, '缺少资源 ID 或名称')
            files = form.getlist('files') if group == 'models' else [form.get('file')]
            if not files or any(not isinstance(item, UploadFile) for item in files):
                raise HTTPException(422, '缺少资源文件')
            paths = []
            for upload in files:
                if not isinstance(upload, UploadFile):
                    raise HTTPException(422, '资源文件格式非法')
                filename = upload.filename or 'content'
                suffix = filename if group == 'models' else 'content'
                await save_upload(store, f'{group}/files/{item_id}/{suffix}', upload)
                paths.append(filename)
            manifest = {'id': item_id, 'name': name, 'files': paths}
            store.write_json(f'{group}/manifests/{item_id}.json', manifest)
            return {'ok': True, **manifest}
    raise HTTPException(501, '该资源操作尚未接入')


async def plugin_resource(request: Request, store: UiStore, parts: list[str]) -> JsonValue | FileResponse:
    """处理立绘和插件编辑器的数据通信协议。

    Args:
        request: 当前资源请求及上传文件。
        store: 已隔离到本浏览器的资源存储。
        parts: 已完成路径检查的路由分段。

    Returns:
        资源 JSON、操作状态或文件响应。

    Raises:
        HTTPException: 路由不支持、文件不存在或上传不合法。
    """
    method, group = request.method, parts[0]
    if group == 'plugins' and len(parts) >= 2:
        collection = f'plugins/{parts[1]}'
        if len(parts) == 2 and method == 'GET':
            directory = store.path(collection)
            return [{'key': p.stem, 'value': store.read_json(f'{collection}/{p.name}')}
                    for p in sorted(directory.glob('*.json'))]
        if len(parts) == 3:
            path = f'{collection}/{parts[2]}.json'
            if method == 'GET':
                return store.read_json(path)
            if method == 'PUT':
                store.write_json(path, await request.json())
                return {'ok': True}
            if method == 'DELETE':
                store.delete(path)
                return {'ok': True}
        if len(parts) == 4 and parts[3] == 'blob':
            path = f'{collection}/blobs/{parts[2]}'
            if method == 'GET':
                return file_response(store, path)
            if method == 'POST':
                form = await request.form()
                upload = form.get('file')
                if not isinstance(upload, UploadFile):
                    raise HTTPException(422, '缺少插件资源文件')
                await save_upload(store, path, upload)
                return {'ok': True, 'url': '/api/userdata/preview/' + '/'.join(parts)}
    raise HTTPException(501, '该资源操作尚未接入')
