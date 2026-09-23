import React from 'react';
import { useApp } from '../../contexts/AppContext';
import SettingSectionTitle from '../ui/SettingSectionTitle';

/** 展示首版固定角色；玩家名称仅用于界面称呼。 */
export default function CharacterTab() {
  const { settings, setSettings } = useApp();
  return (
    <div className="space-y-8 animate-fade-in">
      <SettingSectionTitle title="当前角色设定" />
      <div className="bg-white/60 p-6 rounded-xl border border-[#e6d5b8] space-y-6">
        <p className="font-bold text-[#ba3f42]">亚托莉 · ATRI</p>
        <p className="text-sm text-[#7a6b5d]">当前版本固定与亚托莉对话，暂不支持切换角色或编辑人设。</p>
        <label className="block text-sm text-[#7a6b5d]">玩家名称（仅界面显示）
          <input type="text" value={settings.userName} onChange={e => setSettings({...settings, userName: e.target.value})}
            className="block mt-2 bg-white border border-[#d9c5b2] rounded-md px-4 py-2" />
        </label>
      </div>
    </div>
  );
}
