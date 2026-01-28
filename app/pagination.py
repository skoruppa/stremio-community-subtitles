"""Pagination helper for Quart with async SQLAlchemy"""
from sqlalchemy import select, func
from math import ceil


class Pagination:
    """Simple pagination object compatible with Flask-SQLAlchemy pagination"""
    
    def __init__(self, items, page, per_page, total):
        self.items = items
        self.page = page
        self.per_page = per_page
        self.total = total
    
    @property
    def pages(self):
        """Total number of pages"""
        return ceil(self.total / self.per_page) if self.per_page > 0 else 0
    
    @property
    def has_prev(self):
        """True if a previous page exists"""
        return self.page > 1
    
    @property
    def has_next(self):
        """True if a next page exists"""
        return self.page < self.pages
    
    @property
    def prev_num(self):
        """Number of the previous page"""
        return self.page - 1 if self.has_prev else None
    
    @property
    def next_num(self):
        """Number of the next page"""
        return self.page + 1 if self.has_next else None
    
    def iter_pages(self, left_edge=2, left_current=2, right_current=5, right_edge=2):
        """Iterate over page numbers"""
        last = 0
        for num in range(1, self.pages + 1):
            if num <= left_edge or \
               (num > self.page - left_current - 1 and num < self.page + right_current) or \
               num > self.pages - right_edge:
                if last + 1 != num:
                    yield None
                yield num
                last = num


async def paginate_query(session, query, page, per_page):
    """
    Paginate a SQLAlchemy query
    
    Args:
        session: async SQLAlchemy session
        query: select() query
        page: page number (1-indexed)
        per_page: items per page
    
    Returns:
        Pagination object
    """
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await session.execute(count_query)
    total = count_result.scalar()
    
    # Get items for current page
    items_query = query.offset((page - 1) * per_page).limit(per_page)
    items_result = await session.execute(items_query)
    items = items_result.scalars().all()
    
    return Pagination(items, page, per_page, total)
