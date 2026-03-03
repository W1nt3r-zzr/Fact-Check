"""
网页内容提取模块
从URL中提取干净的文本内容和元信息
"""

import re
import logging
from typing import Dict, Optional, List
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin, urlparse

import httpx
from html2text import HTML2Text

logger = logging.getLogger(__name__)


@dataclass
class ExtractedContent:
    """提取的网页内容"""
    url: str
    title: str
    content: str  # 清理后的纯文本内容
    html: str  # 原始HTML（可选）
    author: Optional[str]
    publish_date: Optional[str]
    meta_description: Optional[str]
    keywords: List[str]
    images: List[str]
    links: List[str]
    extraction_time: str
    word_count: int
    error: Optional[str]


class WebContentExtractor:
    """网页内容提取器"""

    def __init__(
        self,
        timeout: float = 15.0,
        user_agent: str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    ):
        """
        初始化内容提取器

        Args:
            timeout: 请求超时时间（秒）
            user_agent: User-Agent头
        """
        self.timeout = timeout
        self.user_agent = user_agent

        # 配置html2text
        self.h2t = HTML2Text()
        self.h2t.ignore_links = False
        self.h2t.ignore_images = False
        self.h2t.body_width = 0  # 不自动换行
        self.h2t.unicode_snob = True
        self.h2t.ignore_emphasis = False

        # HTTP客户端配置
        self.client_config = {
            "timeout": httpx.Timeout(timeout),
            "follow_redirects": True,
            "max_redirects": 5,
            "headers": {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        }

    async def extract_content(self, url: str) -> ExtractedContent:
        """
        从URL提取网页内容

        Args:
            url: 目标URL

        Returns:
            ExtractedContent: 提取的内容
        """
        extraction_time = datetime.now().isoformat()

        try:
            logger.info(f"开始提取网页内容: {url}")

            async with httpx.AsyncClient(**self.client_config) as client:
                # 发送GET请求
                response = await client.get(url)
                response.raise_for_status()

                html = response.text
                final_url = str(response.url)

                # 提取内容
                title = self._extract_title(html)
                content = self._extract_main_content(html)
                author = self._extract_author(html)
                publish_date = self._extract_publish_date(html)
                meta_description = self._extract_meta_description(html)
                keywords = self._extract_keywords(html)
                images = self._extract_images(html, final_url)
                links = self._extract_links(html, final_url)

                word_count = len(content)

                logger.info(f"内容提取完成: {title}, 字数: {word_count}")

                return ExtractedContent(
                    url=final_url,
                    title=title,
                    content=content,
                    html=html,
                    author=author,
                    publish_date=publish_date,
                    meta_description=meta_description,
                    keywords=keywords,
                    images=images,
                    links=links,
                    extraction_time=extraction_time,
                    word_count=word_count,
                    error=None
                )

        except httpx.TimeoutException:
            logger.error(f"请求超时: {url}")
            return ExtractedContent(
                url=url,
                title="",
                content="",
                html="",
                author=None,
                publish_date=None,
                meta_description=None,
                keywords=[],
                images=[],
                links=[],
                extraction_time=extraction_time,
                word_count=0,
                error="请求超时"
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP错误: {e.response.status_code} - {url}")
            return ExtractedContent(
                url=url,
                title="",
                content="",
                html="",
                author=None,
                publish_date=None,
                meta_description=None,
                keywords=[],
                images=[],
                links=[],
                extraction_time=extraction_time,
                word_count=0,
                error=f"HTTP {e.response.status_code}"
            )

        except Exception as e:
            logger.error(f"内容提取异常: {e}")
            return ExtractedContent(
                url=url,
                title="",
                content="",
                html="",
                author=None,
                publish_date=None,
                meta_description=None,
                keywords=[],
                images=[],
                links=[],
                extraction_time=extraction_time,
                word_count=0,
                error=f"提取异常: {str(e)}"
            )

    def _extract_title(self, html: str) -> str:
        """提取网页标题"""
        # 方法1: 从<title>标签提取
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        if title_match:
            title = title_match.group(1).strip()
            # 清理HTML实体
            title = re.sub(r'<[^>]+>', '', title)
            return title[:200]  # 限制长度

        # 方法2: 从h1标签提取
        h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.IGNORECASE | re.DOTALL)
        if h1_match:
            title = h1_match.group(1).strip()
            title = re.sub(r'<[^>]+>', '', title)
            return title[:200]

        return "未找到标题"

    def _extract_main_content(self, html: str) -> str:
        """提取主要内容"""
        # 使用html2text转换为Markdown格式文本
        try:
            markdown = self.h2t.handle(html)

            # 清理多余的空行
            markdown = re.sub(r'\n\s*\n\s*\n', '\n\n', markdown)

            # 移除过短的行（可能是导航、菜单等噪音）
            lines = markdown.split('\n')
            content_lines = [
                line for line in lines
                if len(line.strip()) > 10 or line.strip().startswith('#')
            ]

            content = '\n'.join(content_lines)

            # 限制长度（避免过长内容）
            if len(content) > 50000:
                content = content[:50000] + "\n\n[内容过长，已截断]"

            return content.strip()

        except Exception as e:
            logger.error(f"内容转换失败: {e}")
            # 降级方案：简单提取<p>标签内容
            paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', html, re.IGNORECASE | re.DOTALL)
            content = '\n\n'.join([
                re.sub(r'<[^>]+>', '', p).strip()
                for p in paragraphs
                if len(re.sub(r'<[^>]+>', '', p).strip()) > 20
            ])
            return content

    def _extract_author(self, html: str) -> Optional[str]:
        """提取作者信息"""
        # 常见的作者meta标签
        patterns = [
            r'<meta[^>]*name=["\']author["\'][^>]*content=["\']([^"\']+)["\']',
            r'<meta[^>]*property=["\']article:author["\'][^>]*content=["\']([^"\']+)["\']',
            r'作者[：:]\s*([^<>\n]{2,20})',
        ]

        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                author = match.group(1).strip()
                # 清理HTML标签
                author = re.sub(r'<[^>]+>', '', author)
                if author and len(author) < 50:
                    return author

        return None

    def _extract_publish_date(self, html: str) -> Optional[str]:
        """提取发布日期"""
        # 常见的日期meta标签
        patterns = [
            r'<meta[^>]*property=["\']article:published_time["\'][^>]*content=["\']([^"\']+)["\']',
            r'<meta[^>]*name=["\']publishdate["\'][^>]*content=["\']([^"\']+)["\']',
            r'<meta[^>]*name=["\']date["\'][^>]*content=["\']([^"\']+)["\']',
            r'发布时间[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?)',
            r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?[\s\d{2}:\d{2}]*',
        ]

        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                date_str = match.group(1).strip()
                # 简单清理
                date_str = re.sub(r'年|月', '-', date_str)
                date_str = re.sub(r'日', '', date_str)
                if date_str and len(date_str) < 30:
                    return date_str

        return None

    def _extract_meta_description(self, html: str) -> Optional[str]:
        """提取元描述"""
        pattern = r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']+)["\']'
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            desc = match.group(1).strip()
            return desc[:200] if desc else None
        return None

    def _extract_keywords(self, html: str) -> List[str]:
        """提取关键词"""
        # 方法1: 从meta标签提取
        meta_pattern = r'<meta[^>]*name=["\']keywords["\'][^>]*content=["\']([^"\']+)["\']'
        match = re.search(meta_pattern, html, re.IGNORECASE)
        if match:
            keywords_str = match.group(1)
            keywords = [kw.strip() for kw in keywords_str.split(',') if kw.strip()]
            return keywords[:10]

        # 方法2: 简单的中文关键词提取（基于词频）
        # 这里只做基础实现，可以后续升级为更高级的NLP算法
        return []

    def _extract_images(self, html: str, base_url: str) -> List[str]:
        """提取图片URL"""
        img_pattern = r'<img[^>]*src=["\']([^"\']+)["\']'
        matches = re.findall(img_pattern, html, re.IGNORECASE)

        # 转换为绝对URL
        images = []
        for img in matches:
            absolute_url = urljoin(base_url, img)
            if absolute_url.startswith('http'):
                images.append(absolute_url)

        return images[:10]  # 限制返回数量

    def _extract_links(self, html: str, base_url: str) -> List[str]:
        """提取链接URL"""
        link_pattern = r'<a[^>]*href=["\']([^"\']+)["\']'
        matches = re.findall(link_pattern, html, re.IGNORECASE)

        # 转换为绝对URL并过滤
        links = []
        seen = set()

        for link in matches:
            # 跳过锚点、javascript等
            if link.startswith('#') or link.startswith('javascript:'):
                continue

            absolute_url = urljoin(base_url, link)

            # 去重
            if absolute_url not in seen and absolute_url.startswith('http'):
                links.append(absolute_url)
                seen.add(absolute_url)

            if len(links) >= 20:  # 限制返回数量
                break

        return links

    async def extract_multiple_contents(
        self,
        urls: List[str],
        concurrent_limit: int = 3
    ) -> List[ExtractedContent]:
        """
        并发提取多个网页内容

        Args:
            urls: URL列表
            concurrent_limit: 并发限制

        Returns:
            List[ExtractedContent]: 提取结果列表
        """
        logger.info(f"开始批量提取 {len(urls)} 个网页内容（并发限制: {concurrent_limit}）")

        import asyncio
        semaphore = asyncio.Semaphore(concurrent_limit)

        async def extract_with_semaphore(url: str):
            async with semaphore:
                return await self.extract_content(url)

        tasks = [extract_with_semaphore(url) for url in urls]
        results = await asyncio.gather(*tasks)

        success_count = sum(1 for r in results if not r.error)
        logger.info(f"批量提取完成: {success_count}/{len(urls)} 成功")

        return results


# 使用示例
async def main():
    """测试网页内容提取"""
    extractor = WebContentExtractor()

    # 测试URL
    test_url = "https://www.gov.cn"

    result = await extractor.extract_content(test_url)

    print(f"URL: {result.url}")
    print(f"标题: {result.title}")
    print(f"作者: {result.author}")
    print(f"发布时间: {result.publish_date}")
    print(f"字数: {result.word_count}")
    print(f"关键词: {result.keywords}")
    print(f"图片数量: {len(result.images)}")
    print(f"链接数量: {len(result.links)}")
    print(f"\n内容摘要:\n{result.content[:500]}...")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
