import os
import requests
import hashlib
from flask import jsonify, request
from flask_login import login_required, current_user
from extensions import db
from models.sticker import UserSticker, PackSticker
from config import Config
from utils import download_sticker_image
from . import sticker_bp

@sticker_bp.route('/api/stickers/hub', methods=['GET'])
@login_required
def get_sticker_hub():
    try:
        sticker_type = request.args.get('type', 'single')
        page = request.args.get('page', 1, type=int)
        
        if sticker_type == 'single':
            response = requests.get(f'{Config.STICKER_API_BASE}/stickerhub', timeout=10)
        else:
            response = requests.get(f'{Config.STICKER_API_BASE}/stickerpackhub', timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            return jsonify({
                'success': True,
                'data': data,
                'type': sticker_type
            })
        else:
            return jsonify({'success': False, 'error': '获取表情包列表失败'}), 500
    except Exception as e:
        print(f"获取表情包列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@sticker_bp.route('/api/stickers/mine', methods=['GET'])
@login_required
def get_my_stickers():
    try:
        sticker_type = request.args.get('type', 'single')
        stickers = UserSticker.query.filter_by(
            user_id=current_user.id,
            sticker_type=sticker_type
        ).all()
        
        return jsonify({
            'success': True,
            'data': [{
                'id': s.id,
                'code': s.sticker_code,
                'name': s.sticker_name,
                'description': s.description,
                'local_path': s.local_path,
                'created_at': s.created_at.strftime('%Y-%m-%d %H:%M:%S')
            } for s in stickers]
        })
    except Exception as e:
        print(f"获取用户表情包失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@sticker_bp.route('/api/stickers/add', methods=['POST'])
@login_required
def add_sticker():
    try:
        data = request.json
        sticker_code = data.get('code')
        sticker_type = data.get('type', 'single')
        
        if not sticker_code:
            return jsonify({'success': False, 'error': '请提供表情码'}), 400
        
        existing = UserSticker.query.filter_by(
            user_id=current_user.id,
            sticker_code=sticker_code
        ).first()
        
        if existing:
            return jsonify({'success': False, 'error': '您已经添加过这个表情了'}), 400
        
        if sticker_type == 'single':
            response = requests.post(
                f'{Config.STICKER_API_BASE}/getsticker',
                json={'code': sticker_code},
                timeout=10
            )
        else:
            response = requests.get(
                f'{Config.STICKER_API_BASE}/getstickerpack',
                params={'code': sticker_code},
                timeout=10
            )
        
        if response.status_code != 200:
            return jsonify({'success': False, 'error': '获取表情信息失败'}), 500
        
        sticker_info = response.json()
        if not sticker_info.get('success'):
            return jsonify({'success': False, 'error': '表情不存在'}), 404
        
        if sticker_type == 'single':
            sticker_data = sticker_info
            image_url = sticker_data.get('url', '')
            sticker_name = sticker_data.get('description', '未命名表情')
            description = sticker_data.get('description', '')
        else:
            sticker_data = sticker_info.get('pack', {})
            image_url = sticker_data.get('cover_url', '')
            sticker_name = sticker_data.get('name', '未命名合集')
            description = sticker_data.get('description', '')
        
        local_path = download_sticker_image(image_url, sticker_code, sticker_type)
        
        if not local_path:
            return jsonify({'success': False, 'error': '下载表情图片失败'}), 500
        
        user_sticker = UserSticker(
            user_id=current_user.id,
            sticker_code=sticker_code,
            sticker_type=sticker_type,
            sticker_name=sticker_name,
            description=description,
            local_path=local_path
        )
        db.session.add(user_sticker)
        
        if sticker_type == 'pack':
            stickers = sticker_data.get('stickers', [])
            print(f"开始下载表情包合集中的 {len(stickers)} 个表情")
            
            for i, sticker in enumerate(stickers):
                try:
                    item_code = sticker.get('code')
                    item_url = sticker.get('url')
                    
                    if not item_code and item_url:
                        item_code = 'url_' + hashlib.md5(item_url.encode()).hexdigest()[:8]
                        print(f"为表情生成code: {item_code}")
                    
                    if item_code and item_url:
                        existing_sticker = PackSticker.query.filter_by(
                            user_id=current_user.id,
                            pack_code=sticker_code,
                            sticker_code=item_code
                        ).first()
                        
                        if not existing_sticker:
                            local_sticker_path = download_sticker_image(
                                item_url, 
                                f"{sticker_code}_{item_code}", 
                                'pack_item'
                            )
                            
                            if local_sticker_path:
                                try:
                                    pack_sticker = PackSticker(
                                        user_id=current_user.id,
                                        pack_code=sticker_code,
                                        sticker_code=item_code,
                                        sticker_name=sticker.get('description', '未命名表情'),
                                        description=sticker.get('description', ''),
                                        local_path=local_sticker_path
                                    )
                                    db.session.add(pack_sticker)
                                    print(f"下载并保存表情 {i+1}/{len(stickers)}: {item_code}")
                                except Exception as db_error:
                                    print(f"保存表情失败 {item_code}: {db_error}")
                                    db.session.rollback()
                                    continue
                        else:
                            print(f"表情已存在，跳过: {item_code}")
                except Exception as e:
                    print(f"下载表情失败 {sticker.get('code', '未知')}: {e}")
                    continue
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': '添加成功',
            'data': {
                'id': user_sticker.id,
                'code': sticker_code,
                'name': sticker_name,
                'description': description,
                'local_path': local_path
            }
        })
    except Exception as e:
        print(f"添加表情包失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@sticker_bp.route('/api/stickers/remove', methods=['POST'])
@login_required
def remove_sticker():
    try:
        data = request.json
        sticker_id = data.get('id')
        
        sticker = UserSticker.query.filter_by(
            id=sticker_id,
            user_id=current_user.id
        ).first()
        
        if not sticker:
            return jsonify({'success': False, 'error': '表情不存在'}), 404
        
        if os.path.exists(sticker.local_path):
            try:
                os.remove(sticker.local_path)
            except:
                pass
        
        db.session.delete(sticker)
        db.session.commit()
        
        return jsonify({'success': True, 'message': '移除成功'})
    except Exception as e:
        print(f"移除表情包失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@sticker_bp.route('/api/stickers/categories', methods=['GET'])
@login_required
def get_sticker_categories():
    try:
        print(f"获取用户 {current_user.id} 的表情包分类")
        
        single_stickers = UserSticker.query.filter_by(
            user_id=current_user.id,
            sticker_type='single'
        ).all()
        
        pack_stickers = UserSticker.query.filter_by(
            user_id=current_user.id,
            sticker_type='pack'
        ).all()
        
        print(f"单个表情数量: {len(single_stickers)}, 表情包合集数量: {len(pack_stickers)}")
        
        categories = []
        
        if single_stickers:
            single_category = {
                'id': 'single',
                'name': '单个表情',
                'type': 'single',
                'icon': 'favorite',
                'stickers': []
            }
            for s in single_stickers:
                try:
                    single_category['stickers'].append({
                        'id': s.id,
                        'code': s.sticker_code,
                        'name': s.sticker_name or '未命名',
                        'local_path': s.local_path
                    })
                except Exception as sticker_error:
                    print(f"处理单个表情失败 {s.id}: {sticker_error}")
                    continue
            categories.append(single_category)
        
        for pack in pack_stickers:
            try:
                categories.append({
                    'id': f'pack_{pack.id}',
                    'name': pack.sticker_name or '未命名合集',
                    'type': 'pack',
                    'code': pack.sticker_code,
                    'icon': pack.local_path,
                    'stickers': []
                })
            except Exception as pack_error:
                print(f"处理表情包合集失败 {pack.id}: {pack_error}")
                continue
        
        print(f"返回分类数量: {len(categories)}")
        
        return jsonify({
            'success': True,
            'data': categories
        })
    except Exception as e:
        import traceback
        print(f"获取表情包分类失败: {e}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

@sticker_bp.route('/api/stickers/pack/<code>', methods=['GET'])
@login_required
def get_pack_stickers(code):
    try:
        print(f"获取表情合集详情: {code}")
        
        user_pack = UserSticker.query.filter_by(
            user_id=current_user.id,
            sticker_code=code,
            sticker_type='pack'
        ).first()
        
        if not user_pack:
            print(f"用户未添加此表情包合集: {code}")
            return jsonify({'success': False, 'error': '您未添加此表情包合集'}), 404
        
        try:
            response = requests.get(
                f'{Config.STICKER_API_BASE}/getstickerpack',
                params={'code': code},
                timeout=10
            )
        except requests.RequestException as req_error:
            print(f"请求表情包服务器失败: {req_error}")
            return jsonify({'success': False, 'error': '无法连接到表情包服务器'}), 503
        
        if response.status_code == 200:
            try:
                data = response.json()
            except ValueError as json_error:
                print(f"解析JSON失败: {json_error}")
                return jsonify({'success': False, 'error': '服务器返回数据格式错误'}), 500
            
            if data.get('success') and data.get('pack'):
                pack = data['pack']
                stickers = pack.get('stickers', [])
                
                print(f"获取到 {len(stickers)} 个表情")
                
                pack_stickers = PackSticker.query.filter_by(
                    user_id=current_user.id,
                    pack_code=code
                ).all()
                
                pack_sticker_map = {ps.sticker_code: ps.local_path for ps in pack_stickers}
                print(f"找到 {len(pack_stickers)} 个已缓存的表情")
                
                processed_stickers = []
                for sticker in stickers:
                    try:
                        sticker_code = sticker.get('code')
                        sticker_url = sticker.get('url')
                        
                        if not sticker_code and sticker_url:
                            sticker_code = 'url_' + hashlib.md5(sticker_url.encode()).hexdigest()[:8]
                        
                        local_path = pack_sticker_map.get(sticker_code)
                        
                        processed_sticker = {
                            'code': sticker_code,
                            'description': sticker.get('description', ''),
                            'url': sticker.get('url', ''),
                            'local_path': local_path,
                            'is_from_pack': True
                        }
                        processed_stickers.append(processed_sticker)
                    except Exception as sticker_error:
                        print(f"处理表情失败: {sticker_error}")
                        continue
                
                return jsonify({
                    'success': True,
                    'data': processed_stickers,
                    'pack_name': pack.get('name', '未命名合集'),
                    'pack_code': code
                })
            else:
                error_msg = data.get('error', '表情合集不存在')
                print(f"表情包服务器返回错误: {error_msg}")
                return jsonify({'success': False, 'error': error_msg}), 404
        else:
            print(f"表情包服务器返回状态码: {response.status_code}")
            return jsonify({'success': False, 'error': f'获取表情合集失败，状态码: {response.status_code}'}), 500
    except Exception as e:
        import traceback
        print(f"获取表情合集详情失败: {e}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500
