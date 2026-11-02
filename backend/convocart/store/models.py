"""Headless store data model: catalog, stock, customers, carts, orders, returns.

This is the commerce backend. The agent layer never imports these models directly;
it talks to the store through `convocart.commerce.CommerceClient`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40), index=True)
    gender: Mapped[str] = mapped_column(String(12), default="unisex")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    price: Mapped[int] = mapped_column(Integer)  # rupees, selling price
    mrp: Mapped[int] = mapped_column(Integer)
    rating: Mapped[float] = mapped_column(Float, default=4.0)
    weight_g: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    variants: Mapped[list["Variant"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    reviews: Mapped[list["Review"]] = relationship(back_populates="product", cascade="all, delete-orphan")


class Variant(Base):
    __tablename__ = "variants"
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    size: Mapped[str] = mapped_column(String(12))
    color: Mapped[str] = mapped_column(String(24))
    stock: Mapped[int] = mapped_column(Integer, default=0)
    product: Mapped[Product] = relationship(back_populates="variants")


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    author: Mapped[str] = mapped_column(String(80))
    rating: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    product: Mapped[Product] = relationship(back_populates="reviews")


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(40))
    preferred_language: Mapped[str] = mapped_column(String(12), default="en")
    reminder_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)  # paid|shipped|delivered|returned|cancelled
    total: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    courier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tracking_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    variant_id: Mapped[str] = mapped_column(ForeignKey("variants.id"))
    title: Mapped[str] = mapped_column(String(200))
    qty: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[int] = mapped_column(Integer)
    order: Mapped[Order] = relationship(back_populates="items")


class Cart(Base):
    __tablename__ = "carts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|checkout|completed
    discount_pct: Mapped[int] = mapped_column(Integer, default=0)
    discount_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    abandoned_event_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    items: Mapped[list["CartItem"]] = relationship(back_populates="cart", cascade="all, delete-orphan")


class CartItem(Base):
    __tablename__ = "cart_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cart_id: Mapped[str] = mapped_column(ForeignKey("carts.id"), index=True)
    variant_id: Mapped[str] = mapped_column(ForeignKey("variants.id"))
    qty: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[int] = mapped_column(Integer)  # copied from the store at add time
    cart: Mapped[Cart] = relationship(back_populates="items")


class ReturnRequest(Base):
    __tablename__ = "returns"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    kind: Mapped[str] = mapped_column(String(12))  # return|exchange|refund
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24))  # pickup_scheduled|pending_approval|approved|rejected
    refund_amount: Mapped[int] = mapped_column(Integer, default=0)
    exchange_size: Mapped[str | None] = mapped_column(String(12), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
