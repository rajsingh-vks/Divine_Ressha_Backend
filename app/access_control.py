from datetime import UTC, datetime

PERMISSION_CATALOG = [
    {
        "code": "profile.manage",
        "name": "Manage profile",
        "group": "account",
        "description": "Update personal account details.",
    },
    {
        "code": "cart.manage",
        "name": "Manage cart",
        "group": "commerce",
        "description": "Add, remove, and update cart items.",
    },
    {
        "code": "checkout.execute",
        "name": "Execute checkout",
        "group": "commerce",
        "description": "Place orders and complete checkout.",
    },
    {
        "code": "wishlist.manage",
        "name": "Manage wishlist",
        "group": "commerce",
        "description": "Save and organize wishlist items.",
    },
    {
        "code": "orders.view_own",
        "name": "View own orders",
        "group": "orders",
        "description": "See customer order history.",
    },
    {
        "code": "reviews.create",
        "name": "Create reviews",
        "group": "engagement",
        "description": "Write product reviews.",
    },
    {
        "code": "addresses.manage",
        "name": "Manage addresses",
        "group": "account",
        "description": "Save shipping and billing addresses.",
    },
    {
        "code": "products.manage",
        "name": "Manage products",
        "group": "catalog",
        "description": "Create and update products.",
    },
    {
        "code": "products.view",
        "name": "View products",
        "group": "catalog",
        "description": "Browse products.",
    },
    {
        "code": "inventory.manage",
        "name": "Manage inventory",
        "group": "inventory",
        "description": "Track and update stock levels.",
    },
    {
        "code": "orders.view",
        "name": "View orders",
        "group": "orders",
        "description": "Review order records.",
    },
    {
        "code": "orders.fulfill",
        "name": "Fulfill orders",
        "group": "orders",
        "description": "Pack and ship customer orders.",
    },
    {
        "code": "payouts.view",
        "name": "View payouts",
        "group": "finance",
        "description": "See payout activity.",
    },
    {
        "code": "reports.view",
        "name": "View reports",
        "group": "analytics",
        "description": "Access performance reports.",
    },
    {
        "code": "customers.manage",
        "name": "Manage customers",
        "group": "users",
        "description": "Review and manage customer accounts.",
    },
    {
        "code": "users.manage",
        "name": "Manage users",
        "group": "users",
        "description": "Create, edit, and deactivate users.",
    },
    {
        "code": "roles.manage",
        "name": "Manage roles",
        "group": "access-control",
        "description": "Create and edit roles.",
    },
    {
        "code": "permissions.manage",
        "name": "Manage permissions",
        "group": "access-control",
        "description": "Assign permissions to roles.",
    },
    {
        "code": "reviews.moderate",
        "name": "Moderate reviews",
        "group": "engagement",
        "description": "Approve or remove reviews.",
    },
    {
        "code": "coupons.manage",
        "name": "Manage coupons",
        "group": "marketing",
        "description": "Create and maintain discounts.",
    },
    {
        "code": "settings.manage",
        "name": "Manage settings",
        "group": "admin",
        "description": "Change system configuration.",
    },
]

DEFAULT_ROLE_TEMPLATES = [
    {
        "name": "customer",
        "description": "Default shopper account.",
        "is_system": True,
        "permissions": [
            "profile.manage",
            "cart.manage",
            "checkout.execute",
            "wishlist.manage",
            "orders.view_own",
            "reviews.create",
            "addresses.manage",
            "products.view",
        ],
    },
    {
        "name": "vendor",
        "description": "Seller or merchant account.",
        "is_system": True,
        "permissions": [
            "profile.manage",
            "products.manage",
            "inventory.manage",
            "orders.view",
            "orders.fulfill",
            "payouts.view",
            "reports.view",
            "products.view",
        ],
    },
    {
        "name": "admin",
        "description": "Platform administrator.",
        "is_system": True,
        "permissions": [permission["code"] for permission in PERMISSION_CATALOG],
    },
]


def current_utc() -> datetime:
    return datetime.now(UTC)
