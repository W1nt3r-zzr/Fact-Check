import { useState, useEffect } from 'react';
import {
  MessageCircle, PlayCircle, Search, Bot, MessageSquare,
  ShieldAlert, MousePointer, Bell, CheckCircle2,
  Home, Compass, User, Settings, Heart, Share2, Bookmark, ThumbsUp,
  ChevronLeft
} from 'lucide-react';

// --- 1. 实验素材数据 (基于你的情景卡片设计) ---

const CONTEXTS = [
  { id: 'c1', title: '家庭微信群', icon: MessageCircle, desc: '长辈正在转发文章', color: 'bg-green-50 border-green-200' },
  { id: 'c2', title: '社交媒体', icon: PlayCircle, desc: '浏览小红书/头条推荐', color: 'bg-red-50 border-red-200' },
  { id: 'c3', title: '知识问答', icon: MessageSquare, desc: '知乎/论坛讨论帖', color: 'bg-blue-50 border-blue-200' },
  { id: 'c4', title: '搜索资料', icon: Search, desc: '写论文查百科', color: 'bg-purple-50 border-purple-200' },
  { id: 'c5', title: 'AI助手对话', icon: Bot, desc: '咨询Kimi/豆包等AI', color: 'bg-indigo-50 border-indigo-200' }
];

const RISKS = [
  { id: 'r1', title: '养生谣言', level: 'low', desc: '热柠檬水能杀癌细胞', riskLabel: '低风险-生活误区' },
  { id: 'r2', title: '财产诈骗', level: 'high', desc: '乡村振兴专项基金认养果树', riskLabel: '高风险-财产损失' },
  { id: 'r3', title: '社会新闻', level: 'med', desc: '某市中心发生重大爆炸事故', riskLabel: '中风险-情绪煽动' }
];

const INTERVENTIONS = [
  { id: 'i1', title: '强力弹窗阻断', type: 'modal', icon: ShieldAlert, desc: '屏幕中央弹出警告框，必须点击才能继续浏览' },
  { id: 'i2', title: '侧边悬浮提示', type: 'bubble', icon: Bell, desc: '右下角出现通知条，可点击查看详情' },
  { id: 'i3', title: '被动右键调用', type: 'menu', icon: MousePointer, desc: '无主动提示，需用户右键选中文字唤起菜单' }
];

export default function ResearchPrototype() {
  // ===== 新实验流程状态 =====
  const [experimentStage, setExperimentStage] = useState('welcome'); // 'welcome' | 'mode-selection' | 'experience' | 'rating' | 'behavior' | 'complete'

  // 风险类型选择（固定）
  const [selectedRisk, setSelectedRisk] = useState(null);

  // 管理员预览模式
  const [isPreviewMode, setIsPreviewMode] = useState(false);

  // 拉丁方设计：用户顺序编号（1-5）
  const [latinSquareOrder, setLatinSquareOrder] = useState(1);

  // 进度追踪
  const [currentScenarioIndex, setCurrentScenarioIndex] = useState(0);

  // 存储数据
  const [allRatings, setAllRatings] = useState([]); // 评分记录
  const [behaviorResponses, setBehaviorResponses] = useState([]); // 每个场景的行为选择

  // 当前场景已体验的模式（用于区分深浅）
  const [experiencedModes, setExperiencedModes] = useState([]);

  // 当前体验的配置
  const [currentContext, setCurrentContext] = useState(null);
  const [currentIntervention, setCurrentIntervention] = useState(null);

  // 评分状态
  const [currentRating, setCurrentRating] = useState({ annoyance: 4, usefulness: 4 });

  // 行为选择状态
  const [selectedAction, setSelectedAction] = useState(null);

  // 场景内模式选择状态
  const [preferredMode, setPreferredMode] = useState(null);

  // ===== 工具函数 =====

  // 拉丁方设计：5种场景顺序
  // 每个顺序都是循环移位，确保每个场景在每个位置出现次数相等
  const LATIN_SQUARE_ORDERS = {
    1: ['c1', 'c2', 'c3', 'c4', 'c5'], // 顺序1: 微信群→社交媒体→知乎→搜索→AI
    2: ['c2', 'c3', 'c4', 'c5', 'c1'], // 顺序2: 社交媒体→知乎→搜索→AI→微信群
    3: ['c3', 'c4', 'c5', 'c1', 'c2'], // 顺序3: 知乎→搜索→AI→微信群→社交媒体
    4: ['c4', 'c5', 'c1', 'c2', 'c3'], // 顺序4: 搜索→AI→微信群→社交媒体→知乎
    5: ['c5', 'c1', 'c2', 'c3', 'c4']  // 顺序5: AI→微信群→社交媒体→知乎→搜索
  };

  // 获取场景顺序（拉丁方设计）
  const getScenarioOrder = () => {
    const order = LATIN_SQUARE_ORDERS[latinSquareOrder];
    // 将场景ID映射到完整的场景对象
    return order.map(contextId => CONTEXTS.find(c => c.id === contextId));
  };

  // 初始化用户顺序编号（随机分配1-5）
  useEffect(() => {
    if (experimentStage === 'welcome') {
      const randomOrder = Math.floor(Math.random() * 5) + 1;
      setLatinSquareOrder(randomOrder);
      console.log(`🎲 用户分配到顺序 ${randomOrder}：`, LATIN_SQUARE_ORDERS[randomOrder]);
    }
  }, []);

  // 获取风险内容
  const getRiskContent = () => {
    if (!selectedRisk) return null;

    // 根据风险类型和场景返回匹配的作者信息
    const getAuthorByRiskAndContext = (riskId, contextId) => {
      // 微信群场景：需要区分文章作者和转发者
      if (contextId === 'c1') {
        // 转发者信息
        const forwarder = '二姨';
        const groupName = '相亲相爱一家人';

        switch (riskId) {
          case 'r1': // 养生谣言
            return {
              articleAuthor: '健康养生大本营', // 文章原始作者
              author: forwarder, // 显示的作者（转发者）
              groupName,
              forwarder: true // 标记这是转发
            };
          case 'r2': // 财产诈骗
            return {
              articleAuthor: '国家政策观察',
              author: forwarder,
              groupName,
              forwarder: true
            };
          case 'r3': // 社会新闻
            return {
              articleAuthor: '新闻快讯官方',
              author: forwarder,
              groupName,
              forwarder: true
            };
        }
      }

      // 社交媒体场景（小红书风格）
      if (contextId === 'c2') {
        switch (riskId) {
          case 'r1': // 养生谣言 - 养生类博主
            const bloggers = ['养生小达人', '健康生活家', '中医养生馆', '食疗养生坊'];
            return { author: bloggers[Math.floor(Math.random() * bloggers.length)] };
          case 'r2': // 财产诈骗 - 财经/政策类博主
            const financeBloggers = ['财经观察员', '政策解读师', '理财小能手', '投资顾问老王'];
            return { author: financeBloggers[Math.floor(Math.random() * financeBloggers.length)] };
          case 'r3': // 社会新闻 - 新闻/资讯类博主
            const newsBloggers = ['实时新闻播报', '城市资讯通', '新闻搬运工', '热点追踪者'];
            return { author: newsBloggers[Math.floor(Math.random() * newsBloggers.length)] };
        }
      }

      // 知乎场景
      if (contextId === 'c3') {
        switch (riskId) {
          case 'r1': // 养生谣言 - 医学/健康领域
            const medicalUsers = ['医学博士李医生', '健康科普专员', '三甲医院主任医师', '营养师小王'];
            return { author: medicalUsers[Math.floor(Math.random() * medicalUsers.length)] };
          case 'r2': // 财产诈骗 - 经济/法律领域
            const financeUsers = ['经济学教授张三', '反诈专家李警官', '金融分析师', '法律顾问王律师'];
            return { author: financeUsers[Math.floor(Math.random() * financeUsers.length)] };
          case 'r3': // 社会新闻 - 新闻/社会领域
            const newsUsers = ['前调查记者', '新闻系教授', '政务账号运营', '社会观察员'];
            return { author: newsUsers[Math.floor(Math.random() * newsUsers.length)] };
        }
      }

      // 搜索引擎场景 - 直接显示来源网站
      if (contextId === 'c4') {
        return { author: null, useSourceAsAuthor: true };
      }

      // AI助手场景
      if (contextId === 'c5') {
        return { author: 'AI助手', isAI: true };
      }

      return { author: null };
    };

    const contextInfo = getAuthorByRiskAndContext(selectedRisk.id, currentContext?.id);

    switch (selectedRisk.id) {
      case 'r1': // 养生谣言 - 热柠檬水
        return {
          title: '《北京协和医院院长发声：热柠檬水只杀癌细胞！切记：多转一人，救人一命！》',
          shortDesc: '热柠檬水能杀癌细胞',
          previewDesc: '北京协和医院陈惠仁教授强调：切片柠檬放入热水中...',
          content: (
            <>
              <p>北京协和医院陈惠仁教授强调：切片柠檬放入热水中，它就会变成"碱性水"，每天饮用对任何人都有益。</p>
              <p>热柠檬水能释放一种苦涩抗癌物质，这是在医药领域有效治疗癌症的最新进展。它只破坏恶性细胞，不影响健康细胞。</p>
              <p className="font-bold text-red-600 mt-4">不管你有多忙，请把这条信息转发给你关心的人！</p>
            </>
          ),
          source: '健康养生大本营',
          author: contextInfo.author,
          articleAuthor: contextInfo.articleAuthor, // 文章原始作者
          useSourceAsAuthor: contextInfo.useSourceAsAuthor, // 是否使用来源作为作者
          groupName: contextInfo.groupName,
          forwarder: contextInfo.forwarder, // 是否为转发
          tags: '#养生健康 #抗癌 #生活小窍门'
        };
      case 'r2': // 财产诈骗 - 乡村振兴基金
        return {
          title: '《内部通知：国家"乡村振兴"专项红利基金开放第二批申领名额！》',
          shortDesc: '乡村振兴专项基金认养果树',
          previewDesc: '为响应国家数字经济发展战略，财政部联合扶贫办特推出...',
          content: (
            <>
              <p>为响应国家数字经济发展战略，财政部联合扶贫办特推出"云数贸"乡村振兴专项扶持项目。</p>
              <p className="font-bold">不看征信，不看户籍，只需下载官方APP并在云端"认养"一棵果树（仅需投入200元激活账户），每天即可获得30元国家分红补贴！</p>
              <p className="font-bold text-red-600">这是国家给普通人的隐形福利，名额有限，点击链接 [s.w.x/cn-fund] 立即激活你的致富账户！</p>
            </>
          ),
          source: '国家政策观察',
          author: contextInfo.author,
          articleAuthor: contextInfo.articleAuthor,
          useSourceAsAuthor: contextInfo.useSourceAsAuthor,
          groupName: contextInfo.groupName,
          forwarder: contextInfo.forwarder,
          tags: '#国家政策 #乡村振兴 #致富'
        };
      case 'r3': // 社会新闻 - 爆炸事故
        return {
          title: '《突发！XX市中心发生重大爆炸事故，现场浓烟滚滚，伤亡人数不明！》',
          shortDesc: '某市中心发生重大爆炸事故',
          previewDesc: '刚刚在XX市科技园附近发生剧烈爆炸，震感强烈！...',
          content: (
            <>
              <p>刚刚在XX市科技园附近发生剧烈爆炸，<span className="font-bold">震感强烈！周围玻璃全被震碎！</span></p>
              <p>目前消防车已赶往现场，听说有大量人员被困。</p>
              <p className="text-gray-500 text-sm mt-2">祈祷平安！🙏 #突发新闻 #现场实拍</p>
            </>
          ),
          source: '新闻快讯官方',
          author: contextInfo.author,
          articleAuthor: contextInfo.articleAuthor,
          useSourceAsAuthor: contextInfo.useSourceAsAuthor,
          groupName: contextInfo.groupName,
          forwarder: contextInfo.forwarder,
          tags: '#突发新闻 #现场实拍 #安全'
        };
      default:
        return null;
    }
  };

  // 初始化当前场景
  useEffect(() => {
    if (experimentStage === 'mode-selection' || experimentStage === 'experience' || experimentStage === 'rating') {
      const scenarios = getScenarioOrder();
      setCurrentContext(scenarios[currentScenarioIndex]);
    }
  }, [currentScenarioIndex, experimentStage]);

  // 选择介入模式并开始体验
  const handleSelectMode = (mode) => {
    setCurrentIntervention(mode);
    setExperimentStage('experience');
  };

  // 保存评分并返回模式选择
  const handleSaveRating = () => {
    const rating = {
      scenarioIndex: currentScenarioIndex,
      contextId: currentContext.id,
      interventionId: currentIntervention.id,
      annoyance: currentRating.annoyance,
      usefulness: currentRating.usefulness,
    };

    setAllRatings([...allRatings, rating]);

    // 添加到已体验列表
    if (!experiencedModes.includes(currentIntervention.id)) {
      setExperiencedModes([...experiencedModes, currentIntervention.id]);
    }

    // 重置评分
    setCurrentRating({ annoyance: 4, usefulness: 4 });

    // 判断下一步：如果3种模式都体验完了，进入偏好选择
    if (experiencedModes.length + 1 >= 3) {
      setExperimentStage('behavior');
    } else {
      // 返回模式选择界面
      setExperimentStage('mode-selection');
    }
  };

  // 保存行为选择并进入下一场景或完成
  const handleSaveBehavior = () => {
    const response = {
      scenarioIndex: currentScenarioIndex,
      contextId: currentContext.id,
      action: selectedAction,
    };
    setBehaviorResponses([...behaviorResponses, response]);
    setSelectedAction(null);
    setPreferredMode(null);

    if (currentScenarioIndex < 4) {
      // 还有更多场景
      setCurrentScenarioIndex(currentScenarioIndex + 1);
      // 重置已体验模式列表
      setExperiencedModes([]);
      setExperimentStage('mode-selection');
    } else {
      // 所有场景都完成了
      setExperimentStage('complete');
    }
  };

  // 获取当前场景的行为选项
  const getActionOptions = () => {
    if (!currentContext) return [];

    switch (currentContext.id) {
      case 'c1': // 家庭微信群
        return [
          { id: 'a1', icon: '🤫', title: '私下发给长辈', desc: '通过私聊分享真相，避免长辈在群里丢脸', color: 'bg-green-50 border-green-200', tag: '温和提醒' },
          { id: 'a2', icon: '👨‍👩‍👧‍👦', title: '转发给其他家人商量', desc: '在小群里讨论，避免直接冲突', color: 'bg-blue-50 border-blue-200', tag: '商议' },
          { id: 'a3', icon: '💬', title: '在群里温和提醒', desc: '委婉地说"这个存疑啊，可以再查查"', color: 'bg-yellow-50 border-yellow-200', tag: '委婉提醒' },
          { id: 'a4', icon: '🤐', title: '不作回应', desc: '选择沉默，避免让长辈难堪', color: 'bg-gray-50 border-gray-200', tag: '沉默' },
          { id: 'a5', icon: '⚠️', title: '在群里直接辟谣', desc: '明确指出这是谣言（可能伤感情）', color: 'bg-red-50 border-red-200', tag: '直接辟谣' }
        ];

      case 'c2': // 社交媒体
        return [
          { id: 'a1', icon: '🚩', title: '举报该内容', desc: '向平台举报虚假信息', color: 'bg-red-50 border-red-200', tag: '举报' },
          { id: 'a2', icon: '⭐', title: '收藏备忘', desc: '收藏下来作为警惕案例', color: 'bg-yellow-50 border-yellow-200', tag: '收藏' },
          { id: 'a3', icon: '📤', title: '分享提醒', desc: '转发给朋友提醒他们注意', color: 'bg-blue-50 border-blue-200', tag: '分享' },
          { id: 'a4', icon: '😶', title: '划走忽略', desc: '不采取任何行动', color: 'bg-gray-50 border-gray-200', tag: '忽略' }
        ];

      case 'c3': // 知乎
        return [
          { id: 'a1', icon: '👍', title: '点赞赞同', desc: '给可信的回答点赞', color: 'bg-green-50 border-green-200', tag: '点赞' },
          { id: 'a2', icon: '💬', title: '评论补充', desc: '在评论区补充更多证据', color: 'bg-blue-50 border-blue-200', tag: '评论' },
          { id: 'a3', icon: '🚩', title: '举报回答', desc: '举报虚假或误导性内容', color: 'bg-red-50 border-red-200', tag: '举报' },
          { id: 'a4', icon: '⭐', title: '收藏备用', desc: '收藏相关信息以备查阅', color: 'bg-yellow-50 border-yellow-200', tag: '收藏' }
        ];

      case 'c4': // 搜索
        return [
          { id: 'a1', icon: '🔍', title: '换个关键词', desc: '尝试其他搜索词验证', color: 'bg-blue-50 border-blue-200', tag: '继续搜索' },
          { id: 'a2', icon: '🔗', title: '点击第一个', desc: '直接点击第一条搜索结果', color: 'bg-green-50 border-green-200', tag: '访问' },
          { id: 'a3', icon: '📋', title: '复制链接', desc: '复制链接分享给他人', color: 'bg-yellow-50 border-yellow-200', tag: '复制' },
          { id: 'a4', icon: '❌', title: '直接离开', desc: '放弃搜索，关闭页面', color: 'bg-gray-50 border-gray-200', tag: '离开' }
        ];

      case 'c5': // AI助手
        return [
          { id: 'a1', icon: '🔄', title: '重新提问', desc: '换一种方式重新询问AI', color: 'bg-blue-50 border-blue-200', tag: '追问' },
          { id: 'a2', icon: '📋', title: '复制结果', desc: '复制AI的回答保存或分享', color: 'bg-yellow-50 border-yellow-200', tag: '复制' },
          { id: 'a3', icon: '🤖', title: '换一个AI', desc: '询问其他AI助手对比答案', color: 'bg-purple-50 border-purple-200', tag: '交叉验证' },
          { id: 'a4', icon: '✅', title: '接受结果', desc: '相信AI的回答并采纳', color: 'bg-green-50 border-green-200', tag: '接受' },
          { id: 'a5', icon: '❌', title: '不再信任', desc: '认为AI不可靠，放弃使用', color: 'bg-red-50 border-red-200', tag: '放弃' }
        ];

      default:
        return [];
    }
  };

  // 根据风险类型获取评论内容
  const getCommentsByRisk = () => {
    if (!selectedRisk) return [];

    switch (selectedRisk.id) {
      case 'r1': // 养生谣言
        return [
          {
            avatar: 'bg-pink-400',
            username: '养生爱好者',
            tag: '健康管理师',
            tagColor: 'bg-blue-100 text-blue-600',
            content: '这个方法我试了，效果真的很好！已经坚持一个月了，感觉身体状态明显改善。',
            time: '1小时前',
            likes: 328
          },
          {
            avatar: 'bg-blue-400',
            username: '李医生',
            tag: '认证医生',
            tagColor: 'bg-green-100 text-green-600',
            content: '作为医学从业者，我必须提醒大家：这个说法没有科学依据。柠檬水确实健康，但不能治疗癌症。请勿轻信谣言。',
            time: '30分钟前',
            likes: 15000
          }
        ];

      case 'r2': // 财产诈骗
        return [
          {
            avatar: 'bg-gradient-to-br from-orange-400 to-red-500',
            username: '受益者',
            tag: null,
            content: '已经投入200元，今天收到了30元分红！太真实了！',
            time: '1小时前',
            likes: 528
          },
          {
            avatar: 'bg-gradient-to-br from-blue-400 to-cyan-500',
            username: '理财达人',
            tag: '财经博主',
            tagColor: 'bg-blue-100 text-blue-600',
            content: '大家小心！这种"认养返利"是典型的传销诈骗模式，前期给甜头，后期卷款跑路。',
            time: '30分钟前',
            likes: 21000
          }
        ];

      case 'r3': // 社会新闻
        return [
          {
            avatar: 'bg-gradient-to-br from-red-400 to-orange-500',
            username: '现场目击者',
            tag: null,
            content: '我当时就在附近，真的吓死人了！整栋楼都在晃，希望大家都平安！',
            time: '20分钟前',
            likes: 3420
          },
          {
            avatar: 'bg-gradient-to-br from-blue-400 to-purple-500',
            username: '新闻观察员',
            tag: '媒体人',
            tagColor: 'bg-purple-100 text-purple-600',
            content: '大家先别慌，等待官方通报。这种未经证实的消息很容易引发恐慌，建议以官方发布为准。',
            time: '15分钟前',
            likes: 8900
          }
        ];

      default:
        return [];
    }
  };

  // 获取知乎回答的补充内容（非风险内容）
  const getZhihuAdditionalAnswers = () => {
    if (!selectedRisk) return [];

    switch (selectedRisk.id) {
      case 'r1': // 养生谣言
        return [
          {
            avatar: 'bg-gradient-to-br from-green-400 to-blue-500',
            username: '科学探索者',
            tag: '科普作者',
            tagColor: 'bg-green-100 text-green-600',
            title: '生物学博士',
            likes: 8600,
            content: (
              <>
                <p>这个说法在科学上是站不住脚的。柠檬水的pH值约为2-3，确实是酸性，不会变成碱性。</p>
                <p className="mt-2">关于"碱性水能治癌"的说法，世界卫生组织早已明确辟谣。癌症的治疗需要专业的医疗手段，不能靠食物来治愈。</p>
                <p className="mt-2">建议大家在看到这类"养生秘方"时，多查证权威来源，不要轻信网络谣言。</p>
              </>
            )
          },
          {
            avatar: 'bg-gradient-to-br from-orange-400 to-red-500',
            username: '理性思考者',
            tag: null,
            title: '普通用户',
            likes: 4200,
            content: (
              <>
                <p>我妈也信这个，之前给她看了好几篇科普文章都不听。后来带她去医院，医生当面给她解释，她才慢慢相信。</p>
                <p className="mt-2">老人家也是为了健康好，只是缺乏科学知识。我们应该耐心引导，而不是一味指责。</p>
              </>
            )
          }
        ];

      case 'r2': // 财产诈骗
        return [
          {
            avatar: 'bg-gradient-to-br from-green-400 to-blue-500',
            username: '反诈志愿者',
            tag: '认证反诈专员',
            tagColor: 'bg-green-100 text-green-600',
            title: '反诈中心',
            likes: 8600,
            content: (
              <>
                <p>这个是典型的传销诈骗！前期用小额返利吸引你投入，后面会要求你继续投更多钱，最后卷款跑路。</p>
                <p className="mt-2">记住：天上不会掉馅饼！凡是"投入少量资金就能获得高额回报"的都是诈骗。请立即停止投资并向公安机关报案。</p>
                <p className="mt-2">建议下载"国家反诈中心"APP，遇到可疑情况及时核实。</p>
              </>
            )
          },
          {
            avatar: 'bg-gradient-to-br from-orange-400 to-red-500',
            username: '受害者',
            tag: null,
            title: '普通用户',
            likes: 4200,
            content: (
              <>
                <p>我之前就遇到过类似的，亏了5000块。前期真的能提现，后来让我投5万才能提现，幸好当时没信。</p>
                <p className="mt-2">大家一定要警惕！这些骗子会伪装成各种国家项目，实际上就是为了骗你的本金。</p>
              </>
            )
          }
        ];

      case 'r3': // 社会新闻
        return [
          {
            avatar: 'bg-gradient-to-br from-blue-400 to-indigo-500',
            username: '官方通报',
            tag: '政务账号',
            tagColor: 'bg-red-100 text-red-600',
            title: '网信办',
            likes: 15600,
            content: (
              <>
                <p>【辟谣声明】经核实，网传"某市中心发生重大爆炸事故"为虚假信息。目前我市秩序正常，未发生此类事件。</p>
                <p className="mt-2">请大家不信谣、不传谣、不造谣，以官方发布信息为准。对故意编造、传播谣言的行为，公安机关将依法追究法律责任。</p>
                <p className="mt-2">如遇类似信息，可通过"中国互联网联合辟谣平台"核实真伪。</p>
              </>
            )
          },
          {
            avatar: 'bg-gradient-to-br from-yellow-400 to-orange-500',
            username: '理性网民',
            tag: null,
            title: '普通用户',
            likes: 6800,
            content: (
              <>
                <p>当时看到这个消息也很慌，赶紧给在那边的朋友发消息。后来朋友说没事，才发现是假消息。</p>
                <p className="mt-2">现在造谣的成本太低了，随便发个消息就能引起社会恐慌。希望平台能加强审核，也希望大家都能冷静一点，看到消息先核实再转发。</p>
              </>
            )
          }
        ];

      default:
        return [];
    }
  };

  // ===== 模拟器组件 =====
  const Simulator = () => {
    const riskContent = getRiskContent();
    if (!riskContent || !currentContext || !currentIntervention) return null;

    // 介入类型：modal（弹窗）、bubble（悬浮）、menu（右键）
    const interventionType = currentIntervention.type;

    // 渲染介入效果的组件
    const InterventionEffect = ({ children }) => {
      // 强力弹窗阻断
      if (interventionType === 'modal') {
        return (
          <div className="relative h-full">
            {children}
            {/* 遮罩层 - 只覆盖模拟器区域 */}
            <div className="absolute inset-0 bg-black/50 flex items-center justify-center z-50 animate-fade-in">
              {/* 弹窗 */}
              <div className="bg-white rounded-xl shadow-2xl max-w-md mx-4 p-6 animate-bounce-in">
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-12 h-12 bg-red-100 rounded-full flex items-center justify-center">
                    <ShieldAlert size={24} className="text-red-600" />
                  </div>
                  <div>
                    <h3 className="font-bold text-lg text-gray-900">⚠️ 警告</h3>
                    <p className="text-sm text-gray-600">AI事实核查提醒</p>
                  </div>
                </div>
                <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4">
                  <p className="text-sm text-red-900">
                    该内容被标记为 <strong>{selectedRisk.riskLabel}</strong>
                  </p>
                  <p className="text-xs text-red-700 mt-2">
                    建议您谨慎对待此信息，可通过官方渠道核实。
                  </p>
                </div>
                <button className="w-full bg-blue-600 text-white py-2 rounded-lg font-medium hover:bg-blue-700 transition-colors">
                  我已了解，继续浏览
                </button>
              </div>
            </div>
          </div>
        );
      }

      // 侧边悬浮提示
      if (interventionType === 'bubble') {
        return (
          <div className="relative h-full">
            {children}
            {/* 右下角悬浮通知 - 紧凑样式 */}
            <div className="absolute bottom-4 right-4 z-50">
              <div className="bg-white rounded-lg shadow-2xl border border-gray-200 overflow-hidden flex items-center">
                {/* 左侧：铃铛图标 + 文字 */}
                <div className="flex items-center gap-2 px-3 py-2 pr-2">
                  <div className="w-6 h-6 bg-orange-100 rounded-full flex items-center justify-center">
                    <Bell size={12} className="text-orange-600" />
                  </div>
                  <span className="text-xs text-gray-800">检测到1条可疑信息</span>
                </div>
                {/* 分隔线 */}
                <div className="w-px h-6 bg-gray-200"></div>
                {/* 右侧：点击查看按钮 */}
                <button className="px-3 py-2 text-xs text-blue-600 hover:bg-blue-50 transition-colors">
                  点击查看
                </button>
              </div>
            </div>
          </div>
        );
      }

      // 被动右键调用（显示右键菜单样式）
      return (
        <div className="relative h-full">
          {children}
          {/* 模拟右键菜单 */}
          <div className="absolute top-20 right-20 z-50">
            <div className="bg-white rounded-lg shadow-2xl border border-gray-300 overflow-hidden min-w-[200px]">
              {/* 菜单标题 */}
              <div className="bg-gray-100 px-3 py-2 border-b border-gray-200">
                <div className="flex items-center gap-2 text-xs text-gray-700">
                  <MousePointer size={12} />
                  <span>AI事实核查</span>
                </div>
              </div>
              {/* 菜单项 */}
              <div className="py-1">
                <div className="px-3 py-2 hover:bg-blue-50 cursor-pointer flex items-center gap-2 text-xs text-gray-700">
                  <ShieldAlert size={14} className="text-orange-500" />
                  <span>核查此内容</span>
                </div>
                <div className="px-3 py-2 hover:bg-blue-50 cursor-pointer flex items-center gap-2 text-xs text-gray-700">
                  <Search size={14} className="text-blue-500" />
                  <span>搜索相关信息</span>
                </div>
              </div>
              <div className="border-t border-gray-200"></div>
              <div className="py-1">
                <div className="px-3 py-2 hover:bg-gray-100 cursor-pointer text-xs text-gray-600">
                  取消
                </div>
              </div>
            </div>
          </div>
        </div>
      );
    };

    // 场景1：家庭微信群 - 左侧聊天列表 + 右侧文章详情页
    if (currentContext.id === 'c1') {
      return (
        <InterventionEffect>
          <div className="h-full bg-gray-100 flex">
            {/* 左侧：微信聊天列表 */}
            <div className="w-72 bg-gray-100 flex flex-col border-r border-gray-200">
              {/* 顶部搜索栏 */}
              <div className="bg-white px-4 py-3 border-b border-gray-200">
                <div className="flex items-center gap-2 bg-gray-100 rounded-lg px-3 py-2">
                  <Search size={16} className="text-gray-400" />
                  <span className="text-sm text-gray-400">搜索</span>
                </div>
              </div>

              {/* 聊天列表 */}
              <div className="flex-1 overflow-y-auto">
                {/* 当前群聊 - 高亮 */}
                <div className="bg-green-100 px-4 py-3 flex items-center gap-3">
                  <div className="w-12 h-12 bg-green-500 rounded-full flex items-center justify-center text-white font-bold">
                    家
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-gray-900 text-sm truncate">{riskContent.groupName}</span>
                      <span className="text-xs text-gray-500 flex-shrink-0 ml-2">12:30</span>
                    </div>
                    <div className="text-xs text-gray-600 mt-0.5 truncate">
                      {riskContent.author}: 分享了一篇文章 👍
                    </div>
                  </div>
                </div>

                {/* 其他群聊/好友 */}
                <div className="bg-white px-4 py-3 flex items-center gap-3 hover:bg-gray-50 border-b border-gray-100">
                  <div className="w-12 h-12 bg-blue-500 rounded-full flex items-center justify-center text-white font-bold">
                    同
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-gray-900 text-sm truncate">同学群</span>
                      <span className="text-xs text-gray-500 flex-shrink-0 ml-2">昨天</span>
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5 truncate">
                      小明: 周末一起打球吗？🏀
                    </div>
                  </div>
                  <div className="w-5 h-5 bg-red-500 rounded-full flex items-center justify-center flex-shrink-0">
                    <span className="text-white text-xs">3</span>
                  </div>
                </div>

                <div className="bg-white px-4 py-3 flex items-center gap-3 hover:bg-gray-50 border-b border-gray-100">
                  <div className="w-12 h-12 bg-purple-500 rounded-full flex items-center justify-center text-white font-bold">
                    公
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-gray-900 text-sm truncate">公司通知群</span>
                      <span className="text-xs text-gray-500 flex-shrink-0 ml-2">周一</span>
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5 truncate">
                      [系统消息] 本周会议安排 📅
                    </div>
                  </div>
                  <div className="w-5 h-5 bg-red-500 rounded-full flex items-center justify-center flex-shrink-0">
                    <span className="text-white text-xs">99</span>
                  </div>
                </div>

                <div className="bg-white px-4 py-3 flex items-center gap-3 hover:bg-gray-50 border-b border-gray-100">
                  <div className="w-12 h-12 bg-gradient-to-br from-pink-400 to-red-500 rounded-full"></div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-gray-900 text-sm truncate">妈妈</span>
                      <span className="text-xs text-gray-500 flex-shrink-0 ml-2">周日</span>
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5 truncate flex items-center gap-1">
                      [语音] 15" <span className="text-gray-400">▶</span>
                    </div>
                  </div>
                </div>

                <div className="bg-white px-4 py-3 flex items-center gap-3 hover:bg-gray-50 border-b border-gray-100">
                  <div className="w-12 h-12 bg-gradient-to-br from-blue-400 to-cyan-500 rounded-full"></div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-gray-900 text-sm truncate">爸爸</span>
                      <span className="text-xs text-gray-500 flex-shrink-0 ml-2">上周</span>
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5 truncate">
                      [转账] ¥200.00
                    </div>
                  </div>
                </div>

                <div className="bg-white px-4 py-3 flex items-center gap-3 hover:bg-gray-50 border-b border-gray-100">
                  <div className="w-12 h-12 bg-gradient-to-br from-orange-400 to-yellow-500 rounded-full"></div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-gray-900 text-sm truncate">二姨</span>
                      <span className="text-xs text-gray-500 flex-shrink-0 ml-2">上周</span>
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5 truncate">
                      朋友圈新动态 📸
                    </div>
                  </div>
                </div>

                <div className="bg-white px-4 py-3 flex items-center gap-3 hover:bg-gray-50 border-b border-gray-100">
                  <div className="w-12 h-12 bg-gradient-to-br from-blue-400 to-cyan-500 rounded-full"></div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-gray-900 text-sm truncate">文件传输助手</span>
                      <span className="text-xs text-gray-500 flex-shrink-0 ml-2">上周</span>
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5 truncate">
                      [文件] 工作报告.pdf
                    </div>
                  </div>
                </div>

                <div className="bg-white px-4 py-3 flex items-center gap-3 hover:bg-gray-50 border-b border-gray-100">
                  <div className="w-12 h-12 bg-gradient-to-br from-green-400 to-emerald-500 rounded-full"></div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-gray-900 text-sm truncate">表弟</span>
                      <span className="text-xs text-gray-500 flex-shrink-0 ml-2">周三</span>
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5 truncate">
                      在吗？有个事想问问 💭
                    </div>
                  </div>
                  <div className="w-5 h-5 bg-red-500 rounded-full flex items-center justify-center flex-shrink-0">
                    <span className="text-white text-xs">1</span>
                  </div>
                </div>
              </div>

              {/* 底部导航栏 */}
              <div className="bg-white px-4 py-3 border-t border-gray-200">
                <div className="flex items-center justify-around">
                  <div className="text-green-600 flex flex-col items-center">
                    <MessageCircle size={20} />
                    <span className="text-xs mt-1">微信</span>
                  </div>
                  <div className="text-gray-400 flex flex-col items-center">
                    <Compass size={20} />
                    <span className="text-xs mt-1">通讯录</span>
                  </div>
                  <div className="text-gray-400 flex flex-col items-center">
                    <Search size={20} />
                    <span className="text-xs mt-1">发现</span>
                  </div>
                  <div className="text-gray-400 flex flex-col items-center">
                    <User size={20} />
                    <span className="text-xs mt-1">我</span>
                  </div>
                </div>
              </div>
            </div>

            {/* 右侧：文章详情页 */}
            <div className="flex-1 bg-gray-50 flex flex-col overflow-hidden">
              {/* 顶部导航栏 - 微信样式 */}
              <div className="bg-[#EDEDED] px-4 py-2 border-b border-[#D6D6D6] flex items-center gap-3">
                <button className="text-gray-700">
                  <ChevronLeft size={20} />
                </button>
                <div className="flex items-center gap-2">
                  <MessageCircle size={16} className="text-gray-600" />
                  <span className="text-xs text-gray-600">来自 {riskContent.groupName}</span>
                </div>
              </div>

              {/* 文章内容区 - 可滚动 */}
              <div className="flex-1 overflow-y-auto bg-[#EDEDED]">
                {/* 作者信息 */}
                <div className="bg-white px-6 py-4 mb-2 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-12 h-12 bg-gradient-to-br from-blue-400 to-purple-500 rounded-full"></div>
                    <div>
                      <div className="font-bold text-sm text-gray-900">{riskContent.articleAuthor || riskContent.source}</div>
                      <div className="text-xs text-gray-500">2小时前</div>
                    </div>
                  </div>
                  <button className="px-4 py-1.5 border border-[#07C160] text-[#07C160] rounded-full text-xs font-medium hover:bg-[#F0F9F4]">
                    关注
                  </button>
                </div>

                {/* 文章封面图 */}
                <div className="bg-white mb-2">
                  <div className="w-full h-48 bg-gradient-to-br from-orange-100 via-orange-200 to-orange-300 flex items-center justify-center relative overflow-hidden">
                    <div className="absolute inset-0 opacity-10">
                      <div className="w-full h-full" style={{backgroundImage: 'repeating-linear-gradient(45deg, transparent, transparent 10px, #000 10px, #000 20px)', backgroundSize: '20px 20px'}}></div>
                    </div>
                    <div className="text-center z-10">
                      <div className="text-6xl mb-2">📰</div>
                      <div className="text-sm font-medium text-gray-700">健康养生资讯</div>
                    </div>
                  </div>
                </div>

                {/* 文章标题卡片 */}
                <div className="bg-white px-6 py-4 mb-2">
                  <h1 className="text-xl font-bold text-gray-900 mb-2 leading-snug">{riskContent.title}</h1>
                  <div className="text-xs text-gray-500 flex items-center gap-2">
                    <span>原创</span>
                    <span>·</span>
                    <span>阅读 10万+</span>
                    <span>·</span>
                    <span>点赞 2.3万</span>
                  </div>
                </div>

                {/* 文章正文卡片 */}
                <div className="bg-white px-6 py-4 mb-2">
                  <div className="text-sm text-gray-800 space-y-3 leading-relaxed">
                    {riskContent.content}
                  </div>
                  {/* 文章底部互动提示 */}
                  <div className="mt-4 pt-3 border-t border-gray-100 flex items-center justify-between text-xs text-gray-500">
                    <span>分享到朋友圈</span>
                    <div className="flex items-center gap-1">
                      <span className="flex items-center gap-1">
                        <span>点赞</span>
                        <span className="text-orange-500">❤️</span>
                      </span>
                    </div>
                  </div>
                </div>

                {/* 公众号信息卡片 */}
                <div className="bg-white px-6 py-4 mb-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 bg-gradient-to-br from-blue-400 to-purple-500 rounded-full"></div>
                      <div>
                        <div className="font-bold text-sm text-gray-900">{riskContent.articleAuthor || riskContent.source}</div>
                        <div className="text-xs text-gray-500">功能介绍</div>
                      </div>
                    </div>
                    <button className="px-4 py-1.5 bg-[#07C160] text-white rounded-full text-xs font-medium">
                      关注公众号
                    </button>
                  </div>
                  <div className="text-xs text-gray-500 mt-2 flex items-center gap-1">
                    <span>✅ 认证</span>
                    <span>功能介绍：分享健康养生知识，传递科学养生理念</span>
                  </div>
                </div>

                {/* 评论区 */}
                <div className="bg-white px-6 py-4">
                  <div className="text-sm font-bold text-gray-900 mb-4">精选留言</div>
                  <div className="space-y-4">
                    {getCommentsByRisk().map((comment, idx) => (
                      <div key={idx} className={`flex gap-3 ${idx < getCommentsByRisk().length - 1 ? 'pb-3 border-b border-gray-100' : ''}`}>
                        <div className={`w-8 h-8 ${comment.avatar} rounded-full flex-shrink-0`}></div>
                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="font-medium text-xs text-gray-900">{comment.username}</span>
                            {comment.tag && (
                              <span className={`text-xs px-2 py-0.5 rounded ${comment.tagColor}`}>{comment.tag}</span>
                            )}
                          </div>
                          <p className="text-xs text-gray-800 mb-1">{comment.content}</p>
                          <div className="text-xs text-gray-500">{comment.time} · 回复 · {comment.likes >= 1000 ? (comment.likes / 10000).toFixed(1) + '万' : comment.likes}</div>
                        </div>
                        <div className="flex flex-col items-center gap-1 text-gray-400">
                          <button className="hover:text-orange-500">👍</button>
                          <button className="text-xs hover:text-blue-500">回复</button>
                        </div>
                      </div>
                    ))}
                  </div>
                  {/* 写评论输入框 */}
                  <div className="mt-4 pt-3 border-t border-gray-100">
                    <div className="flex items-center gap-2 bg-gray-100 rounded-full px-4 py-2">
                      <input
                        type="text"
                        placeholder="写留言..."
                        className="flex-1 bg-transparent outline-none text-xs"
                      />
                      <button className="text-xs text-gray-500">😊</button>
                    </div>
                  </div>
                </div>
              </div>

              {/* 底部操作栏 - 固定 */}
              <div className="bg-[#F7F7F7] border-t border-[#D6D6D6] px-4 py-2">
                <div className="flex items-center justify-between text-xs text-gray-600">
                  <div className="flex items-center gap-4">
                    <div className="flex items-center gap-1 cursor-pointer hover:text-gray-900">
                      <MessageSquare size={16} />
                      <span>{456}</span>
                    </div>
                    <div className="flex items-center gap-1 cursor-pointer hover:text-gray-900">
                      <ThumbsUp size={16} />
                      <span>2.3万</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button className="bg-[#07C160] text-white px-3 py-1 rounded-lg text-xs font-medium hover:bg-[#06AD56]">
                      写评论
                    </button>
                    <button className="text-gray-600 hover:text-gray-900">
                      <Share2 size={18} />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </InterventionEffect>
      );
    }

    // 场景2：社交媒体 - 详情页（小红书风格）
    if (currentContext.id === 'c2') {
      return (
        <InterventionEffect>
          <div className="h-full bg-gray-50 flex">
            {/* 左侧导航栏 - 缩窄至64px */}
            <div className="w-16 bg-white border-r border-gray-200 flex flex-col items-center py-4">
              <div className="text-red-500 mb-6">
                <div className="w-10 h-10 bg-red-500 rounded-full flex items-center justify-center">
                  <PlayCircle size={20} className="text-white" />
                </div>
              </div>
              <div className="flex-1 flex flex-col gap-6">
                <div className="text-gray-400 hover:text-gray-800 cursor-pointer">
                  <Home size={24} />
                </div>
                <div className="text-gray-800 cursor-pointer">
                  <Compass size={24} />
                </div>
                <div className="text-gray-400 hover:text-gray-800 cursor-pointer">
                  <MessageSquare size={24} />
                </div>
                <div className="text-gray-400 hover:text-gray-800 cursor-pointer">
                  <User size={24} />
                </div>
              </div>
              <div className="text-gray-400 hover:text-gray-800 cursor-pointer">
                <Settings size={24} />
              </div>
            </div>

            {/* 主内容区 */}
            <div className="flex-1 overflow-y-auto">
              <div className="max-w-2xl mx-auto bg-white min-h-full">
                {/* 作者信息 */}
                <div className="p-4 flex items-center justify-between border-b border-gray-100">
                  <div className="flex items-center gap-3">
                    <div className="w-14 h-14 bg-gradient-to-br from-pink-400 to-red-500 rounded-full p-0.5">
                      <img
                        src={`https://api.dicebear.com/7.x/${riskContent.author}/200`}
                        alt="avatar"
                        className="w-full h-full rounded-full"
                      />
                    </div>
                    <div>
                      <div className="font-bold text-base text-gray-900">{riskContent.author}</div>
                      <div className="text-xs text-gray-500 flex items-center gap-1">
                        <span>2小时前</span>
                        <span>·</span>
                        <span>北京</span>
                      </div>
                      <div className="text-xs text-gray-400 mt-0.5">
                        粉丝 {Math.floor(Math.random() * 10) + 5}万 · 获赞 {Math.floor(Math.random() * 50) + 10}万
                      </div>
                    </div>
                  </div>
                  <button className="px-5 py-2 border border-red-500 text-red-500 rounded-full text-sm font-medium hover:bg-red-50 transition-colors">
                    关注
                  </button>
                </div>

                {/* 图片/视频区域 - 多图轮播 */}
                <div className="grid grid-cols-3 gap-1 aspect-square p-1 bg-gray-50">
                  {[1, 2, 3, 4, 5, 6].slice(0, 3).map((_, idx) => (
                    <div key={idx} className="relative bg-gradient-to-br from-orange-100 to-orange-200 rounded-lg overflow-hidden group cursor-pointer">
                      <div className="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-all flex items-center justify-center">
                        <PlayCircle size={40} className="text-white opacity-80" />
                      </div>
                    </div>
                  ))}
                </div>

                {/* 标题和操作栏 */}
                <div className="p-4">
                  {/* 标题 */}
                  <h1 className="font-bold text-base text-gray-900 mb-2 line-clamp-2">
                    {riskContent.title}
                  </h1>

                  {/* 标签 */}
                  <div className="flex gap-2 mb-3 flex-wrap">
                    <span className="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">
                      {selectedRisk?.id === 'r1' ? '💡 生活小技巧' :
                     selectedRisk?.id === 'r2' ? '💰 理财投资' :
                     '📰 热点资讯'}
                    </span>
                    {riskContent.tags.split(' ').map((tag, i) => (
                      <span key={i} className="text-xs text-blue-500 bg-blue-50 px-2 py-1 rounded-full">
                        {tag}
                      </span>
                    ))}
                  </div>

                  {/* 内容 */}
                  <div className="mb-4">
                    <p className="text-sm text-gray-800 mb-2 leading-relaxed">
                      {riskContent.previewDesc}
                    </p>
                    <p className="text-sm text-gray-800 leading-relaxed">
                      {riskContent.title}
                    </p>
                  </div>

                  {/* 展开/收起按钮 */}
                  <button className="text-sm text-gray-500 hover:text-gray-700 mb-3">
                    展开全文 <span className="text-xs">▼</span>
                  </button>

                  {/* 正文内容 */}
                  <div className="prose prose-sm text-gray-700 space-y-2 mb-4">
                    {riskContent.content}
                  </div>

                  {/* 互动统计 */}
                  <div className="flex items-center gap-4 text-xs text-gray-500 mb-3">
                    <div className="flex items-center gap-1">
                      <Heart size={14} />
                      <span>{Math.floor(Math.random() * 5000 + 1000)}</span>
                    </div>
                    <div className="flex items-center gap-1">
                      <MessageCircle size={14} />
                      <span>{Math.floor(Math.random() * 500 + 100)}</span>
                    </div>
                    <div className="flex items-center gap-1">
                      <Bookmark size={14} />
                      <span>{Math.floor(Math.random() * 200 + 50)}</span>
                    </div>
                    <div className="flex items-center gap-1">
                      <Share2 size={14} />
                      <span>{Math.floor(Math.random() * 100 + 20)}</span>
                    </div>
                  </div>

                  {/* 收藏夹 */}
                  <div className="bg-gray-50 rounded-lg p-3 mb-3">
                    <div className="text-xs text-gray-600 mb-2 flex items-center gap-1">
                      <Bookmark size={12} />
                      <span>收藏到</span>
                    </div>
                    <div className="flex gap-2">
                      {['健康养生', '生活百科', '必读好文', '每日分享'].map((folder, idx) => (
                        <button key={idx} className="text-xs bg-white px-3 py-1 rounded-full border border-gray-200 hover:bg-gray-50 transition-all">
                          {folder}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* 发布时间 */}
                  <div className="text-xs text-gray-400">
                    编辑于 {new Date().toLocaleDateString('zh-CN')} {new Date().toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'})}
                  </div>
                </div>

                {/* 评论区 */}
                <div className="border-t border-gray-100">
                  {/* 评论区标题 */}
                  <div className="p-4 border-b border-gray-100">
                    <div className="flex items-center justify-between">
                      <div className="text-sm font-bold text-gray-900">
                        评论 ({Math.floor(Math.random() * 200 + 50)})
                      </div>
                      <div className="flex items-center gap-2 text-xs text-gray-500">
                        <button className="hover:text-gray-800">按热度</button>
                        <span>·</span>
                        <button className="hover:text-gray-800">按时间</button>
                      </div>
                    </div>
                  </div>

                  {/* 评论列表 */}
                  <div className="p-4 space-y-4">
                    {getCommentsByRisk().slice(0, 2).map((comment, idx) => (
                      <div key={idx} className="flex gap-3">
                        <div className={`w-9 h-9 ${comment.avatar} rounded-full flex-shrink-0`}></div>
                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="font-medium text-sm text-gray-900">{comment.username}</span>
                            {comment.tag && (
                              <span className={`text-xs px-2 py-0.5 rounded ${comment.tagColor}`}>{comment.tag}</span>
                            )}
                          </div>
                          <p className="text-sm text-gray-800 mb-2 leading-relaxed">{comment.content}</p>
                          <div className="flex items-center gap-4 text-xs text-gray-500">
                            <span>{comment.time}</span>
                            <button className="hover:text-gray-700">回复</button>
                            <button className="hover:text-red-500 flex items-center gap-0.5">
                              <Heart size={12} />
                              <span>{comment.likes >= 1000 ? (comment.likes / 10000).toFixed(1) + 'w' : comment.likes}</span>
                            </button>
                          </div>
                          {/* 快速回复框 */}
                          <div className="mt-2 flex items-center gap-2">
                            <input
                              type="text"
                              placeholder={`回复 ${comment.username}...`}
                              className="flex-1 text-xs bg-gray-100 rounded-full px-3 py-1.5 outline-none focus:ring-2 focus:ring-blue-200"
                            />
                            <button className="text-xs text-blue-500 font-medium hover:text-blue-700">
                              发送
                            </button>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {/* 右侧推荐栏 - 缩窄至224px */}
            <div className="w-56 bg-white border-l border-gray-200 p-3 hidden lg:block">
              <div className="text-sm font-bold text-gray-500 mb-4">为你推荐</div>
              <div className="space-y-4">
                <div className="flex gap-3 cursor-pointer hover:bg-gray-50 transition-colors rounded-lg p-2">
                  <div className="w-20 h-20 bg-gradient-to-br from-pink-200 to-red-200 rounded-lg flex-shrink-0"></div>
                  <div className="flex-1">
                    <div className="text-xs text-gray-800 line-clamp-2 font-medium">小红书爆款护肤分享</div>
                    <div className="flex items-center gap-1 mt-1">
                      <span className="text-xs text-gray-500">❤️ 1.2w</span>
                      <span className="text-xs text-gray-500">💬 56</span>
                    </div>
                  </div>
                </div>
                <div className="flex gap-3 cursor-pointer hover:bg-gray-50 transition-colors rounded-lg p-2">
                  <div className="w-20 h-20 bg-gradient-to-br from-blue-200 to-purple-200 rounded-lg flex-shrink-0"></div>
                  <div className="flex-1">
                    <div className="text-xs text-gray-800 line-clamp-2 font-medium">职场新人必看技巧</div>
                    <div className="flex items-center gap-1 mt-1">
                      <span className="text-xs text-gray-500">❤️ 8.9k</span>
                      <span className="text-xs text-gray-500">💬 234</span>
                    </div>
                  </div>
                </div>
                <div className="flex gap-3 cursor-pointer hover:bg-gray-50 transition-colors rounded-lg p-2">
                  <div className="w-20 h-20 bg-gradient-to-br from-green-200 to-emerald-200 rounded-lg flex-shrink-0"></div>
                  <div className="flex-1">
                    <div className="text-xs text-gray-800 line-clamp-2 font-medium">健康饮食指南</div>
                    <div className="flex items-center gap-1 mt-1">
                      <span className="text-xs text-gray-500">❤️ 3.4k</span>
                      <span className="text-xs text-gray-500">💬 89</span>
                    </div>
                  </div>
                </div>
                <div className="flex gap-3 cursor-pointer hover:bg-gray-50 transition-colors rounded-lg p-2">
                  <div className="w-20 h-20 bg-gradient-to-br from-yellow-200 to-orange-200 rounded-lg flex-shrink-0"></div>
                  <div className="flex-1">
                    <div className="text-xs text-gray-800 line-clamp-2 font-medium">家常菜谱合集</div>
                    <div className="flex items-center gap-1 mt-1">
                      <span className="text-xs text-gray-500">❤️ 5.6k</span>
                      <span className="text-xs text-gray-500">💬 156</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* 相关话题标签 */}
              <div className="border-t border-gray-100 pt-3 mt-3">
                <div className="text-xs font-medium text-gray-700 mb-2">相关话题</div>
                <div className="flex flex-wrap gap-2">
                  {['#生活技巧', '#健康养生', '#理财知识', '#日常分享', '#好物推荐'].map((tag, idx) => (
                    <span key={idx} className="text-xs text-gray-600 bg-gray-100 px-2 py-1 rounded-full hover:bg-gray-200 cursor-pointer transition-all">
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </InterventionEffect>
      );
    }

    // 场景3：知乎 - 详情页（高保真）
    if (currentContext.id === 'c3') {
      return (
        <InterventionEffect>
          <div className="h-full bg-white flex flex-col">
            {/* 顶部导航栏 */}
            <div className="bg-white px-4 py-3 border-b border-gray-200 flex items-center justify-between sticky top-0 z-10">
              <div className="flex items-center gap-6">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
                    <MessageSquare size={18} className="text-white" />
                  </div>
                  <span className="font-bold text-lg text-gray-900">知乎</span>
                </div>
                <div className="flex items-center gap-2 bg-gray-100 rounded-full px-4 py-2 flex-1 max-w-xl">
                  <Search size={18} className="text-gray-400" />
                  <input
                    type="text"
                    placeholder={riskContent.shortDesc}
                    className="bg-transparent outline-none text-sm flex-1"
                    readOnly
                  />
                </div>
              </div>
              <div className="flex items-center gap-4">
                <button className="text-gray-600 hover:text-gray-900 text-sm">提问</button>
                <button className="text-gray-600 hover:text-gray-900 text-sm">登录</button>
              </div>
            </div>

            {/* 问题区域 */}
            <div className="bg-gray-50 border-b border-gray-200">
              <div className="max-w-3xl mx-auto px-6 py-6">
                <h1 className="text-2xl font-bold text-gray-900 mb-3">
                  {riskContent.title}是真的吗？
                </h1>
                <div className="flex items-center gap-3 text-sm text-gray-500">
                  <span>{riskContent.previewDesc}</span>
                  <button className="text-blue-600 hover:text-blue-700">关注问题</button>
                  <span>·</span>
                  <span>328 个回答</span>
                </div>
              </div>
            </div>

            {/* 回答列表 */}
            <div className="flex-1 overflow-y-auto">
              <div className="max-w-3xl mx-auto">
                {/* 回答1 - 高赞回答 */}
                <div className="px-6 py-6 border-b border-gray-200">
                  <div className="flex items-start gap-3 mb-4">
                    <div className="w-10 h-10 bg-gradient-to-br from-blue-400 to-purple-500 rounded-full flex-shrink-0"></div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-bold text-blue-600">{riskContent.author}</span>
                        <span className="bg-blue-100 text-blue-600 text-xs px-2 py-0.5 rounded">优秀回答者</span>
                      </div>
                      <div className="text-xs text-gray-500">1.2万赞同</div>
                    </div>
                  </div>

                  <div className="prose prose-sm text-gray-800 mb-4">
                    {riskContent.content}
                  </div>

                  <div className="flex items-center justify-between text-sm text-gray-500">
                    <div className="flex items-center gap-6">
                      <button className="flex items-center gap-1 hover:text-blue-600">
                        <ThumbsUp size={18} />
                        <span>1.2万</span>
                      </button>
                      <button className="flex items-center gap-1 hover:text-blue-600">
                        <MessageSquare size={18} />
                        <span>328条评论</span>
                      </button>
                      <button className="hover:text-blue-600">收藏</button>
                      <button className="hover:text-blue-600">分享</button>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs">已收藏 5600+</span>
                    </div>
                  </div>
                </div>

                {/* 回答2-3：动态补充回答 */}
                {getZhihuAdditionalAnswers().map((answer, idx) => (
                  <div key={idx} className={`px-6 py-6 ${idx === 0 ? 'border-b border-gray-200' : ''}`}>
                    <div className="flex items-start gap-3 mb-4">
                      <div className={`w-10 h-10 ${answer.avatar} rounded-full flex-shrink-0`}></div>
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-bold text-blue-600">{answer.username}</span>
                          {answer.tag && (
                            <span className={`text-xs px-2 py-0.5 rounded ${answer.tagColor}`}>{answer.tag}</span>
                          )}
                        </div>
                        <div className="text-xs text-gray-500">{answer.title} · {answer.likes >= 1000 ? (answer.likes / 10000).toFixed(1) + '万' : answer.likes}赞同</div>
                      </div>
                    </div>

                    <div className="prose prose-sm text-gray-800 mb-4">
                      {answer.content}
                    </div>

                    <div className="flex items-center gap-6 text-sm text-gray-500">
                      <button className="flex items-center gap-1 hover:text-blue-600">
                        <ThumbsUp size={18} />
                        <span>{answer.likes >= 1000 ? (answer.likes / 10000).toFixed(1) + '万' : answer.likes}</span>
                      </button>
                      <button className="flex items-center gap-1 hover:text-blue-600">
                        <MessageSquare size={18} />
                        <span>{idx === 0 ? '156' : '89'}条评论</span>
                      </button>
                      <button className="hover:text-blue-600">收藏</button>
                      <button className="hover:text-blue-600">分享</button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </InterventionEffect>
      );
    }

    // 场景4：搜索引擎 - 详情页（百度/谷歌风格）
    if (currentContext.id === 'c4') {
      return (
        <InterventionEffect>
          <div className="h-full bg-white overflow-y-auto">
            {/* 顶部搜索栏 */}
            <div className="bg-white border-b border-gray-200 p-3 sticky top-0 z-10">
              <div className="max-w-3xl mx-auto">
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-2 text-blue-500 font-bold text-xl">
                    <Search size={24} />
                    <span>搜索</span>
                  </div>
                  <div className="flex-1 flex items-center gap-2 bg-gray-100 rounded-full px-4 py-2 border-2 border-transparent hover:border-gray-300 hover:bg-white transition-all">
                    <Search size={16} className="text-gray-400" />
                    <input
                      type="text"
                      value={riskContent.shortDesc}
                      readOnly
                      className="flex-1 outline-none text-sm bg-transparent"
                    />
                  </div>
                </div>
              </div>
            </div>

            {/* 搜索结果区 */}
            <div className="max-w-3xl mx-auto p-4">
              {/* 统计信息 */}
              <div className="text-xs text-gray-500 mb-4">
                找到约 1,230,000 条结果 （用时 0.42 秒）
              </div>

              {/* 搜索结果1 - 主结果 */}
              <div className="mb-6">
                <div className="flex items-center gap-2 mb-1">
                  <div className="w-6 h-6 bg-blue-600 rounded flex items-center justify-center">
                    <span className="text-white text-xs font-bold">搜</span>
                  </div>
                  <div>
                    <div className="text-sm text-gray-800">{riskContent.source}</div>
                    <div className="text-xs text-gray-500">https://www.{riskContent.source}.com/article/12345</div>
                  </div>
                </div>
                <a className="text-xl text-blue-800 hover:underline font-medium cursor-pointer block mb-1">
                  {riskContent.title}
                </a>
                <p className="text-sm text-gray-600 mb-2">{riskContent.previewDesc}</p>
                <div className="text-sm text-gray-700 leading-relaxed bg-green-50 p-3 rounded-lg border border-green-100">
                  <p className="mb-2">{riskContent.content}</p>
                  <div className="flex items-center gap-2 text-xs text-green-700">
                    <span className="bg-green-100 px-2 py-0.5 rounded">官方认证</span>
                    <span>2小时前发布</span>
                  </div>
                </div>
              </div>

              {/* 搜索结果2 - 相关结果 */}
              <div className="border-t border-gray-200 pt-4 mb-4">
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-5 h-5 bg-green-600 rounded flex items-center justify-center">
                    <span className="text-white text-xs font-bold">百</span>
                  </div>
                  <div>
                    <div className="text-sm text-gray-800">健康科普网</div>
                    <div className="text-xs text-gray-500">https://www.health-science.cn {'>'} 热点话题</div>
                  </div>
                </div>
                <a className="text-lg text-blue-800 hover:underline font-medium cursor-pointer block mb-1">
                  {selectedRisk.id === 'r1' ? '专家辟谣：热柠檬水不能治疗癌症，这些才是科学的抗癌方法' :
                     selectedRisk.id === 'r2' ? '⚠️ 警惕！"乡村振兴基金"诈骗套路大揭秘，已有数千人被骗' :
                     '官方辟谣：网传某市爆炸事故为虚假信息，请勿轻信谣言'}
                </a>
                <p className="text-sm text-gray-600">
                  {selectedRisk.id === 'r1' ? '近日，一则关于"热柠檬水杀癌细胞"的消息在网络上广泛传播。经核实，该说法缺乏科学依据...' :
                     selectedRisk.id === 'r2' ? '多地公安部门发布预警：近期出现以"乡村振兴"为名的集资诈骗活动，请广大市民提高警惕...' :
                     '经相关部门核实，网传"某市发生重大爆炸事故"为不实信息。目前该市秩序正常...'}
                </p>
              </div>

              {/* 搜索结果3 - 百科词条 */}
              <div className="border-t border-gray-200 pt-4 mb-4">
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-5 h-5 bg-blue-500 rounded flex items-center justify-center">
                    <span className="text-white text-xs font-bold">百</span>
                  </div>
                  <div>
                    <div className="text-sm text-gray-800">百科词条</div>
                    <div className="text-xs text-gray-500">https://baike.baidu.com/item/...</div>
                  </div>
                </div>
                <a className="text-lg text-blue-800 hover:underline font-medium cursor-pointer block mb-1">
                  {selectedRisk.id === 'r1' ? '柠檬 - 维基百科，自由的百科全书' :
                     selectedRisk.id === 'r2' ? '网络诈骗 - 百度百科' :
                     '虚假信息 - 百度百科'}
                </a>
                <p className="text-sm text-gray-600">
                  {selectedRisk.id === 'r1' ? '柠檬（学名：Citrus × limon）是芸香科柑橘属植物。关于柠檬水的健康功效，科学研究表明...' :
                     selectedRisk.id === 'r2' ? '网络诈骗是指利用互联网采用虚构事实或者隐瞒真相的方法，骗取数额较大的公私财物的行为...' :
                     '虚假信息是指不真实、不准确的信息。在互联网时代，虚假信息的传播速度和范围都大大增加...'}
                </p>
              </div>

              {/* 相关搜索推荐 */}
              <div className="bg-gray-50 rounded-lg p-4 mt-6">
                <div className="text-sm font-medium text-gray-700 mb-3">大家还在搜</div>
                <div className="flex flex-wrap gap-2">
                  {selectedRisk.id === 'r1' ? [
                    '柠檬水真的抗癌吗',
                    '碱性水治癌症真相',
                    '协和医院辟谣',
                    '养生谣言大全',
                    '科学抗癌方法'
                  ] : selectedRisk.id === 'r2' ? [
                    '乡村振兴基金诈骗',
                    '国家反诈中心APP',
                    '如何识别投资诈骗',
                    '云数贸传销',
                    '政府项目查询'
                  ] : [
                    '今日突发新闻',
                    '如何辨别网络谣言',
                    '官方辟谣平台',
                    '谣言止于智者',
                    '网络信息真实性查询'
                  ].map((term, idx) => (
                    <span key={idx} className="text-xs bg-white px-3 py-1.5 rounded-full border border-gray-200 text-gray-700 cursor-pointer hover:bg-blue-50 hover:text-blue-600 hover:border-blue-300 transition-all">
                      🔍 {term}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </InterventionEffect>
      );
    }

    // 场景5：AI助手 - 详情页（Kimi/豆包风格）
    if (currentContext.id === 'c5') {
      return (
        <InterventionEffect>
          <div className="h-full bg-white flex flex-col">
            {/* 顶部导航栏 */}
            <div className="bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-purple-600 rounded-lg flex items-center justify-center">
                  <Bot size={18} className="text-white" />
                </div>
                <div>
                  <div className="font-bold text-sm text-gray-900">AI 智能助手</div>
                  <div className="text-xs text-gray-500">随时为您解答疑问</div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button className="text-xs text-gray-600 hover:text-gray-900 px-3 py-1.5 rounded-full border border-gray-200 hover:border-gray-300">
                  清空对话
                </button>
              </div>
            </div>

            {/* 对话区域 */}
            <div className="flex-1 overflow-y-auto bg-gray-50">
              <div className="max-w-3xl mx-auto py-6 px-4 space-y-6">
                {/* 用户问题 */}
                <div className="flex justify-end">
                  <div className="bg-blue-600 text-white px-4 py-3 rounded-2xl rounded-tr-sm max-w-lg shadow-sm">
                    <p className="text-sm">请问 {riskContent.shortDesc} 是真的吗？</p>
                  </div>
                  <div className="w-8 h-8 bg-gradient-to-br from-blue-400 to-cyan-500 rounded-full ml-2 flex-shrink-0"></div>
                </div>

                {/* AI 回复 */}
                <div className="flex justify-start">
                  <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-purple-600 rounded-full mr-2 flex-shrink-0 flex items-center justify-center">
                    <Bot size={16} className="text-white" />
                  </div>
                  <div className="bg-white border border-gray-200 rounded-2xl rounded-tl-sm p-4 max-w-2xl shadow-sm">
                    {/* 思考状态 */}
                    <div className="flex items-center gap-2 mb-3 pb-3 border-b border-gray-100">
                      <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
                      <span className="text-xs text-gray-500">已为您检索相关信息</span>
                    </div>

                    {/* 主要回复内容 */}
                    <div className="text-sm text-gray-800 space-y-3 mb-4">
                      <p className="font-medium">您好！关于您提到的内容，我为您查证了相关信息：</p>
                      <div className="bg-blue-50 p-3 rounded-lg border-l-4 border-blue-500">
                        <p className="text-xs text-blue-900 mb-2 font-medium">
                          {selectedRisk.id === 'r1' ? '⚠️ 该说法缺乏科学依据' :
                           selectedRisk.id === 'r2' ? '⚠️ 这是典型的诈骗信息' :
                           '⚠️ 该信息真实性存疑'}
                        </p>
                        <div className="text-sm text-gray-700 leading-relaxed">
                          {riskContent.content}
                        </div>
                      </div>
                    </div>

                    {/* 引用来源 */}
                    <div className="mt-4 pt-3 border-t border-gray-100">
                      <div className="text-xs text-gray-500 mb-2 flex items-center gap-1">
                        <Search size={12} />
                        <span>参考来源：</span>
                      </div>
                      <div className="space-y-2">
                        {selectedRisk.id === 'r1' ? [
                          { source: '北京协和医院官网', desc: '官方辟谣声明' },
                          { source: '世界卫生组织 (WHO)', desc: '癌症治疗官方指南' },
                          { source: '丁香医生', desc: '《柠檬水真的能抗癌吗？科普文章》' }
                        ] : selectedRisk.id === 'r2' ? [
                          { source: '国家反诈中心', desc: '官方诈骗预警' },
                          { source: '公安部网站', desc: '关于"云数贸"诈骗的通报' },
                          { source: '中国银行保险报', desc: '乡村振兴政策权威解读' }
                        ] : [
                          { source: '当地公安局官方微博', desc: '辟谣声明' },
                          { source: '中国互联网联合辟谣平台', desc: '经核实为虚假信息' },
                          { source: '网信办', desc: '关于网络谣言的提醒' }
                        ].map((ref, idx) => (
                          <div key={idx} className="flex items-start gap-2 text-xs bg-gray-50 px-3 py-2 rounded-lg hover:bg-blue-50 cursor-pointer transition-colors">
                            <div className="w-5 h-5 bg-blue-100 rounded flex items-center justify-center flex-shrink-0 mt-0.5">
                              <span className="text-blue-600 text-xs font-bold">{idx + 1}</span>
                            </div>
                            <div className="flex-1">
                              <div className="font-medium text-gray-800">{ref.source}</div>
                              <div className="text-gray-500">{ref.desc}</div>
                            </div>
                            <ChevronLeft size={12} className="text-gray-400 rotate-180 mt-1" />
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* 底部操作 */}
                    <div className="mt-4 pt-3 border-t border-gray-100 flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <button className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1">
                          👍 有帮助
                        </button>
                        <button className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1">
                          👎 无帮助
                        </button>
                        <button className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1">
                          📋 复制
                        </button>
                      </div>
                      <span className="text-xs text-gray-400">AI生成内容，请谨慎参考</span>
                    </div>
                  </div>
                </div>

                {/* 追问建议 */}
                <div className="pl-10">
                  <div className="text-xs text-gray-500 mb-2">您可能还想了解：</div>
                  <div className="flex flex-wrap gap-2">
                    {selectedRisk.id === 'r1' ? [
                      '有什么科学依据吗？',
                      '哪些食物真的抗癌？',
                      '如何识别养生谣言？'
                    ] : selectedRisk.id === 'r2' ? [
                      '如何识别投资诈骗？',
                      '正规的乡村振兴政策是什么？',
                      '遇到诈骗怎么办？'
                    ] : [
                      '如何辨别新闻真假？',
                      '哪里可以查证信息？',
                      '网络谣言有什么危害？'
                    ].map((question, idx) => (
                      <button key={idx} className="text-xs bg-white px-3 py-1.5 rounded-full border border-gray-200 text-gray-700 hover:bg-blue-50 hover:text-blue-600 hover:border-blue-300 transition-all">
                        {question}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {/* 输入框 */}
            <div className="border-t border-gray-200 bg-white p-4">
              <div className="max-w-3xl mx-auto">
                <div className="flex items-end gap-3 border-2 border-gray-200 rounded-xl px-4 py-3 bg-white focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-100 transition-all">
                  <textarea
                    placeholder="继续提问..."
                    rows="1"
                    className="flex-1 outline-none text-sm resize-none"
                    style={{ minHeight: '24px' }}
                  />
                  <div className="flex items-center gap-2">
                    <button className="text-gray-400 hover:text-gray-600 p-1">
                      <Share2 size={18} />
                    </button>
                    <button className="bg-blue-600 text-white px-4 py-1.5 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors flex items-center gap-1">
                      <span>发送</span>
                      <Bot size={14} />
                    </button>
                  </div>
                </div>
                <div className="text-xs text-gray-400 mt-2 text-center">
                  AI 可能会生成错误信息，请核实重要内容
                </div>
              </div>
            </div>
          </div>
        </InterventionEffect>
      );
    }

    return <div className="flex items-center justify-center h-full text-gray-400">加载中...</div>;
  };

  // ===== 渲染 =====

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50">
      {/* 顶部标题栏 */}
      <header className="bg-white/80 backdrop-blur-sm border-b border-gray-200 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-blue-600 to-purple-600 rounded-xl flex items-center justify-center text-white font-bold">
              AI
            </div>
            <div>
              <h1 className="font-bold text-gray-900">AI事实核查系统用户研究</h1>
              <p className="text-xs text-gray-500">体验不同的AI介入方式</p>
            </div>
          </div>

          {/* 进度指示 */}
          {selectedRisk && (experimentStage === 'mode-selection' || experimentStage === 'experience' || experimentStage === 'rating' || experimentStage === 'behavior') && (
            <div className="flex items-center gap-4">
              <div className="text-sm">
                <span className="text-gray-600">场景 {currentScenarioIndex + 1}/5</span>
                <span className="mx-2 text-gray-400">·</span>
                <span className="text-gray-600">已体验 {experiencedModes.length}/3 种模式</span>
              </div>
              {isPreviewMode && (
                <div className="bg-yellow-100 text-yellow-800 text-xs px-3 py-1 rounded-full font-medium">
                  管理员预览模式
                </div>
              )}
            </div>
          )}
        </div>
      </header>

      {/* 主内容区 */}
      <main className="max-w-7xl mx-auto px-4 py-8">
        {/* 阶段1：欢迎页 + 风险类型选择 */}
        {experimentStage === 'welcome' && (
          <div className="max-w-2xl mx-auto">
            <div className="bg-white rounded-2xl shadow-lg p-8 mb-6">
              <h2 className="text-2xl font-bold mb-4 text-center">欢迎参与AI事实核查系统用户研究</h2>

              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
                <h3 className="font-bold text-sm text-blue-900 mb-2">实验说明</h3>
                <ul className="text-sm text-blue-800 space-y-2">
                  <li>• 您将体验 <strong>5个使用场景</strong>（微信群、社交媒体、知乎、搜索引擎、AI助手）</li>
                  <li>• 每个场景包含 <strong>3种AI介入方式</strong>（弹窗阻断、悬浮气泡、右键菜单）</li>
                  <li>• 体验每种介入方式后，请快速评价（烦躁度、有用度）</li>
                  <li>• 完成一个场景的所有介入方式后，选择您最喜欢的方式</li>
                  <li>• 预计耗时：<strong>15-20分钟</strong></li>
                </ul>
              </div>

              {/* 管理员预览模式开关 */}
              <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-6">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-bold text-sm text-gray-900 mb-2">管理员预览模式</h3>
                    <p className="text-xs text-gray-500">开启后可快速预览所有场景，无需完成全部评分</p>
                  </div>
                  <button
                    onClick={() => setIsPreviewMode(!isPreviewMode)}
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                      isPreviewMode ? 'bg-blue-600' : 'bg-gray-300'
                    }`}
                  >
                    <span
                      className={`inline-block w-4 h-4 rounded-full bg-white transform transition-transform ${
                        isPreviewMode ? 'translate-x-6' : 'translate-x-1'
                      }`}
                    />
                  </button>
                </div>
              </div>

              {/* 用户顺序编号显示 */}
              <div className="bg-purple-50 border border-purple-200 rounded-lg p-4 mb-6">
                <div className="flex items-center justify-between">
                  <div className="flex-1">
                    <h3 className="font-bold text-sm text-purple-900 mb-2">🎲 您的场景顺序</h3>
                    <div className="text-sm text-purple-800">
                      <div className="mb-1">顺序编号：<strong>{latinSquareOrder}</strong> / 5</div>
                      <div className="text-xs mt-2">
                        场景顺序：{LATIN_SQUARE_ORDERS[latinSquareOrder].map((id, idx) => {
                          const context = CONTEXTS.find(c => c.id === id);
                          return (
                            <span key={id} className="inline-block">
                              <span className="font-medium">{idx + 1}. {context?.title}</span>
                              {idx < 4 ? <span className="mx-1 text-purple-400">→</span> : null}
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={() => {
                      const newOrder = (latinSquareOrder % 5) + 1;
                      setLatinSquareOrder(newOrder);
                      console.log(`🎲 切换到顺序 ${newOrder}：`, LATIN_SQUARE_ORDERS[newOrder]);
                    }}
                    className="text-xs text-purple-600 hover:text-purple-800 px-3 py-1 rounded-full border border-purple-300 hover:bg-purple-100 transition-all"
                  >
                    🔄 换一个
                  </button>
                </div>
              </div>

              <h3 className="text-lg font-bold mb-4">请选择您要体验的风险类型：</h3>
              <div className="space-y-3">
                {RISKS.map(risk => (
                  <button
                    key={risk.id}
                    onClick={() => setSelectedRisk(risk)}
                    className={`w-full p-5 rounded-xl border-2 text-left transition-all hover:shadow-md ${
                      selectedRisk?.id === risk.id
                        ? 'border-blue-500 bg-blue-50 ring-2 ring-blue-200'
                        : 'border-gray-200 hover:border-blue-300'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="font-bold text-lg text-gray-900">{risk.title}</div>
                        <div className="text-sm text-gray-500 mt-1">{risk.desc}</div>
                      </div>
                      <span className={`text-sm px-3 py-1 rounded-full ${
                        risk.level === 'high' ? 'bg-red-100 text-red-700' :
                        risk.level === 'med' ? 'bg-yellow-100 text-yellow-700' :
                        'bg-gray-100 text-gray-700'
                      }`}>
                        {risk.riskLabel}
                      </span>
                    </div>
                  </button>
                ))}
              </div>

              <div className="mt-8 flex justify-end">
                <button
                  onClick={() => setExperimentStage('mode-selection')}
                  disabled={!selectedRisk}
                  className={`px-8 py-3 rounded-xl font-bold transition-all ${
                    selectedRisk
                      ? 'bg-blue-600 text-white hover:bg-blue-700 shadow-lg hover:shadow-xl'
                      : 'bg-gray-100 text-gray-400 cursor-not-allowed'
                  }`}
                >
                  开始实验 →
                </button>
              </div>
            </div>
          </div>
        )}

        {/* 阶段1：模式选择界面 */}
        {experimentStage === 'mode-selection' && currentContext && (
          <div className="max-w-3xl mx-auto">
            <div className="bg-white rounded-2xl shadow-lg p-8 mb-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-2xl font-bold text-center flex-1">选择介入模式体验</h2>
                <button
                  onClick={() => setExperimentStage('welcome')}
                  className="text-gray-500 hover:text-gray-700 text-sm flex items-center gap-1"
                >
                  ← 返回
                </button>
              </div>
              <p className="text-center text-gray-500 mb-6">
                场景 {currentScenarioIndex + 1}/5：<strong>{currentContext.title}</strong>
              </p>

              {/* 管理员预览模式：场景快速选择器 */}
              {isPreviewMode && (
                <div className="bg-purple-50 border border-purple-200 rounded-lg p-4 mb-6">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-bold text-purple-900">⚡ 快速跳转场景</h3>
                    <span className="text-xs text-purple-700">管理员专属</span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {CONTEXTS.map((context, idx) => (
                      <button
                        key={context.id}
                        onClick={() => {
                          setCurrentScenarioIndex(idx);
                          setExperiencedModes([]);
                        }}
                        className={`px-3 py-2 rounded-lg text-sm font-medium transition-all ${
                          currentScenarioIndex === idx
                            ? 'bg-purple-600 text-white shadow-md'
                            : 'bg-white text-gray-700 border border-purple-200 hover:bg-purple-100'
                        }`}
                      >
                        <span className="flex items-center gap-2">
                          <context.icon size={16} />
                          <span>{idx + 1}. {context.title}</span>
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
                <p className="text-sm text-blue-900">
                  <strong>💡 说明：</strong>请选择一种介入模式进行体验。已体验的模式会显示为<strong>深色</strong>，未体验的模式显示为<strong>浅色</strong>。完成全部3种模式体验后，进入下一阶段。
                </p>
              </div>

              <div className="space-y-3 mb-6">
                {INTERVENTIONS.map(mode => {
                  const isExperienced = experiencedModes.includes(mode.id);
                  return (
                    <button
                      key={mode.id}
                      onClick={() => handleSelectMode(mode)}
                      className={`w-full p-5 rounded-xl border-2 text-left transition-all hover:shadow-md ${
                        isExperienced
                          ? 'bg-blue-100 border-blue-400 hover:border-blue-500'
                          : 'bg-white border-gray-200 hover:border-blue-300'
                      }`}
                    >
                      <div className="flex items-start gap-4">
                        <div className={`p-3 rounded-lg ${isExperienced ? 'bg-blue-200' : 'bg-gray-100'}`}>
                          <mode.icon size={24} className="text-gray-600" />
                        </div>
                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="font-bold text-lg text-gray-900">{mode.title}</span>
                            {isExperienced && (
                              <span className="bg-blue-500 text-white text-xs px-2 py-0.5 rounded-full">已体验</span>
                            )}
                          </div>
                          <div className="text-sm text-gray-500">{mode.desc}</div>
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>

              <div className="text-center text-sm text-gray-500">
                已体验 {experiencedModes.length}/3 种模式
              </div>
            </div>
          </div>
        )}

        {/* 阶段2：体验界面 */}
        {experimentStage === 'experience' && currentContext && currentIntervention && (
          <div className="grid md:grid-cols-2 gap-8 items-start">
            {/* 左侧：控制面板 */}
            <div className="bg-white p-6 rounded-2xl shadow-lg">
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h2 className="text-xl font-bold mb-1">场景 {currentScenarioIndex + 1}/5：{currentContext.title}</h2>
                  <p className="text-sm text-gray-500">{currentContext.desc}</p>
                </div>
                <button
                  onClick={() => setExperimentStage('mode-selection')}
                  className="text-gray-500 hover:text-gray-700 text-sm flex items-center gap-1"
                >
                  ← 返回
                </button>
              </div>

              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
                <div className="text-sm text-blue-900 mb-2">
                  <strong>当前体验：</strong>
                </div>
                <div className="flex gap-2 flex-wrap text-sm text-blue-800">
                  <span className="bg-white px-2 py-1 rounded">{currentContext.title}</span>
                  <span className="bg-white px-2 py-1 rounded font-bold">{currentIntervention.title}</span>
                </div>
              </div>

              <div className="mb-6">
                <h3 className="text-sm font-bold text-gray-700 mb-3">AI介入方式说明：</h3>
                <div className="bg-gray-50 rounded-lg p-4">
                  <div className="flex items-start gap-3">
                    <div className="p-2 bg-white rounded-lg">
                      <currentIntervention.icon size={24} className="text-gray-600" />
                    </div>
                    <div>
                      <div className="font-bold text-gray-900">{currentIntervention.title}</div>
                      <div className="text-sm text-gray-500 mt-1">{currentIntervention.desc}</div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mb-6">
                <p className="text-sm text-yellow-900">
                  <strong>💡 提示：</strong>请在右侧模拟器中仔细体验该介入方式，体验完成后点击下方按钮进行评价。
                </p>
              </div>

              <button
                onClick={() => setExperimentStage('rating')}
                className="w-full bg-blue-600 text-white py-3 rounded-xl font-bold hover:bg-blue-700 transition-colors"
              >
                我已经体验好了，去评价 →
              </button>
            </div>

            {/* 右侧：模拟器 */}
            <div className="flex items-center justify-center sticky top-8">
              <div className="w-[1200px] h-[650px] border-4 border-gray-300 rounded-lg overflow-hidden bg-white shadow-2xl relative">
                <Simulator />
              </div>
            </div>
          </div>
        )}

        {/* 阶段3：快速评分 */}
        {experimentStage === 'rating' && (
          <div className="max-w-xl mx-auto">
            <div className="bg-white rounded-2xl shadow-lg p-8">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-xl font-bold text-center flex-1">请评价刚才的AI介入方式</h2>
                <button
                  onClick={() => setExperimentStage('experience')}
                  className="text-gray-500 hover:text-gray-700 text-sm flex items-center gap-1"
                >
                  ← 返回
                </button>
              </div>

              <div className="mb-6 bg-gray-50 rounded-lg p-4">
                <div className="text-sm text-gray-700 mb-2">
                  <strong>您刚才体验的是：</strong>
                </div>
                <div className="flex gap-2 flex-wrap text-sm">
                  <span className="bg-white px-2 py-1 rounded">{currentContext?.title}</span>
                  <span className="bg-white px-2 py-1 rounded font-bold">{currentIntervention?.title}</span>
                </div>
              </div>

              <div className="space-y-8">
                {/* 烦躁程度 */}
                <div>
                  <div className="flex justify-between mb-3">
                    <label className="font-medium text-gray-700">刚才的AI提示让您觉得烦吗？</label>
                    <span className="font-bold text-blue-600 text-lg">{currentRating.annoyance}</span>
                  </div>
                  <input
                    type="range" min="1" max="7"
                    value={currentRating.annoyance}
                    onChange={(e) => setCurrentRating({...currentRating, annoyance: parseInt(e.target.value)})}
                    className="w-full h-3 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                  />
                  <div className="flex justify-between text-xs text-gray-500 mt-2">
                    <span>1 = 完全不烦</span>
                    <span>7 = 非常烦</span>
                  </div>
                </div>

                {/* 有用程度 */}
                <div>
                  <div className="flex justify-between mb-3">
                    <label className="font-medium text-gray-700">您觉得这个提示对判断真假有帮助吗？</label>
                    <span className="font-bold text-blue-600 text-lg">{currentRating.usefulness}</span>
                  </div>
                  <input
                    type="range" min="1" max="7"
                    value={currentRating.usefulness}
                    onChange={(e) => setCurrentRating({...currentRating, usefulness: parseInt(e.target.value)})}
                    className="w-full h-3 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                  />
                  <div className="flex justify-between text-xs text-gray-500 mt-2">
                    <span>1 = 完全没用</span>
                    <span>7 = 非常有帮助</span>
                  </div>
                </div>
              </div>

              <button
                onClick={handleSaveRating}
                className="w-full mt-8 bg-blue-600 text-white py-3 rounded-xl font-bold hover:bg-blue-700 transition-colors"
              >
                {experiencedModes.length + 1 >= 3 ? '完成所有模式体验 →' : '返回选择下一个模式 →'}
              </button>

              {/* 预览模式：跳过评分和偏好选择 */}
              {isPreviewMode && (
                <button
                  onClick={() => {
                    // 直接跳到下一场景
                    if (currentScenarioIndex < 4) {
                      setCurrentScenarioIndex(currentScenarioIndex + 1);
                      setExperiencedModes([]);
                      setExperimentStage('mode-selection');
                    } else {
                      setExperimentStage('complete');
                    }
                  }}
                  className="w-full mt-3 bg-gray-500 text-white py-2 rounded-lg font-medium hover:bg-gray-600 transition-colors text-sm"
                >
                  ⚡ 预览模式：跳过评分，直接进入下一场景
                </button>
              )}
            </div>
          </div>
        )}

        {/* 阶段4：选择最喜欢的模式 */}
        {experimentStage === 'behavior' && !preferredMode && (
          <div className="max-w-2xl mx-auto">
            <div className="bg-white rounded-2xl shadow-lg p-8">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-xl font-bold text-center flex-1">您已经体验完本场景的3种介入方式</h2>
                <button
                  onClick={() => setExperimentStage('mode-selection')}
                  className="text-gray-500 hover:text-gray-700 text-sm flex items-center gap-1"
                >
                  ← 返回
                </button>
              </div>
              <p className="text-center text-gray-500 mb-6">请选择您最喜欢的介入方式：</p>

              <div className="mb-6 bg-gray-50 rounded-lg p-4">
                <div className="text-sm text-gray-700">
                  <strong>场景 {currentScenarioIndex + 1}/5：</strong>{currentContext?.title}
                </div>
              </div>

              <div className="space-y-3 mb-8">
                {INTERVENTIONS.map(mode => (
                  <button
                    key={mode.id}
                    onClick={() => setPreferredMode(mode)}
                    className={`w-full p-5 rounded-xl border-2 text-left transition-all hover:shadow-md ${
                      preferredMode?.id === mode.id
                        ? 'border-blue-500 bg-blue-50 ring-2 ring-blue-200'
                        : 'border-gray-200 hover:border-blue-300'
                    }`}
                  >
                    <div className="flex items-start gap-4">
                      <div className="p-3 bg-gray-100 rounded-lg">
                        <mode.icon size={24} className="text-gray-600" />
                      </div>
                      <div className="flex-1">
                        <div className="font-bold text-lg text-gray-900">{mode.title}</div>
                        <div className="text-sm text-gray-500 mt-1">{mode.desc}</div>
                      </div>
                      {preferredMode?.id === mode.id && (
                        <CheckCircle2 className="text-blue-500" size={24} />
                      )}
                    </div>
                  </button>
                ))}
              </div>

              <button
                onClick={() => setExperimentStage('behavior')}
                disabled={!preferredMode}
                className={`w-full py-3 rounded-xl font-bold transition-all ${
                  preferredMode
                    ? 'bg-blue-600 text-white hover:bg-blue-700 shadow-lg'
                    : 'bg-gray-100 text-gray-400 cursor-not-allowed'
                }`}
              >
                确认选择，继续 →
              </button>
            </div>
          </div>
        )}

        {/* 阶段5：行为选择问题 */}
        {experimentStage === 'behavior' && preferredMode && (
          <div className="max-w-2xl mx-auto">
            <div className="bg-white rounded-2xl shadow-lg p-8">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-xl font-bold text-center flex-1">最后一个问题</h2>
                <button
                  onClick={() => setPreferredMode(null)}
                  className="text-gray-500 hover:text-gray-700 text-sm flex items-center gap-1"
                >
                  ← 返回
                </button>
              </div>
              <p className="text-center text-gray-500 mb-6">
                在<strong>{currentContext?.title}</strong>场景中，如果使用<strong>{preferredMode?.title}</strong>介入，您会怎么做？
              </p>

              <div className="space-y-3 mb-8">
                {getActionOptions().map(action => (
                  <button
                    key={action.id}
                    onClick={() => setSelectedAction(action)}
                    className={`w-full p-4 rounded-xl border-2 text-left transition-all hover:shadow-md ${
                      selectedAction?.id === action.id
                        ? `${action.color} ring-2 ring-blue-500`
                        : action.color
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      <div className="text-2xl">{action.icon}</div>
                      <div className="flex-1">
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-bold text-gray-900">{action.title}</span>
                          <span className="text-xs bg-white px-2 py-0.5 rounded-full">{action.tag}</span>
                        </div>
                        <div className="text-xs text-gray-600">{action.desc}</div>
                      </div>
                      {selectedAction?.id === action.id && (
                        <CheckCircle2 className="text-blue-500" size={20} />
                      )}
                    </div>
                  </button>
                ))}
              </div>

              <button
                onClick={handleSaveBehavior}
                disabled={!selectedAction}
                className={`w-full py-3 rounded-xl font-bold transition-all ${
                  selectedAction
                    ? 'bg-blue-600 text-white hover:bg-blue-700 shadow-lg'
                    : 'bg-gray-100 text-gray-400 cursor-not-allowed'
                }`}
              >
                {currentScenarioIndex < 4 ? '进入下一场景 →' : '完成实验 →'}
              </button>
            </div>
          </div>
        )}

        {/* 阶段6：实验完成 */}
        {experimentStage === 'complete' && (
          <div className="max-w-2xl mx-auto">
            <div className="bg-white rounded-2xl shadow-lg p-8 text-center">
              <div className="w-20 h-20 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-6">
                <CheckCircle2 size={40} className="text-green-600" />
              </div>

              <h2 className="text-2xl font-bold mb-4">实验完成！</h2>
              <p className="text-gray-600 mb-8">
                感谢您完成所有5个场景的体验。您的反馈对我们改进AI事实核查系统非常有价值。
              </p>

              <div className="bg-green-50 border border-green-200 rounded-lg p-6 mb-8 text-left">
                <h3 className="font-bold text-green-900 mb-4">数据统计：</h3>
                <div className="space-y-2 text-sm text-green-800">
                  <div className="flex justify-between">
                    <span>场景顺序编号：</span>
                    <span className="font-bold">{latinSquareOrder} / 5</span>
                  </div>
                  <div className="flex justify-between">
                    <span>场景顺序：</span>
                    <span className="font-bold text-xs">
                      {LATIN_SQUARE_ORDERS[latinSquareOrder].map((id, idx) => {
                        const context = CONTEXTS.find(c => c.id === id);
                        return `${idx + 1}.${context?.title}`;
                      }).join(' → ')}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>完成的场景数：</span>
                    <span className="font-bold">5/5</span>
                  </div>
                  <div className="flex justify-between">
                    <span>体验的介入方式：</span>
                    <span className="font-bold">15次（5场景×3模式）</span>
                  </div>
                  <div className="flex justify-between">
                    <span>提供的评分：</span>
                    <span className="font-bold">{allRatings.length}条</span>
                  </div>
                  <div className="flex justify-between">
                    <span>选择的偏好模式：</span>
                    <span className="font-bold">{behaviorResponses.length}个</span>
                  </div>
                </div>
              </div>

              <div className="bg-blue-50 border border-blue-200 rounded-lg p-6 mb-8">
                <h3 className="font-bold text-blue-900 mb-3">下一步：完成后测问卷</h3>
                <p className="text-sm text-blue-800 mb-4">
                  请点击下方按钮填写后测问卷，分享您对AI事实核查系统的整体体验和反馈。
                </p>
                <a
                  href="https://www.wenjuanxing.com/"  // 替换为实际的后测问卷链接
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-block bg-blue-600 text-white px-8 py-3 rounded-xl font-bold hover:bg-blue-700 transition-colors"
                >
                  填写后测问卷 →
                </a>
              </div>

              <div className="text-xs text-gray-500">
                <p>所有数据将严格保密，仅用于学术研究。</p>
                <p className="mt-1">如有疑问，请联系研究者。</p>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
