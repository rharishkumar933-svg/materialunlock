from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.database.mongo import db
import uuid

# Temporary storage for campaign data during creation
campaign_drafts = {}

@Client.on_callback_query(filters.regex(r"^new_campaign$"))
async def new_campaign_start(client, callback_query):
    user_id = callback_query.from_user.id
    channels = await db.get_creator_channels(user_id)
    
    if not channels:
        await callback_query.answer("❌ Please connect a channel first!", show_alert=True)
        return

    await callback_query.message.edit_text(
        "![✍](tg://emoji?id=6030433657552903637) **Step 1: Enter Campaign Title**\n\n"
        "Please send a name for your campaign (e.g., 'Premium Movies').",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="creator_dashboard", icon_custom_emoji_id="5985574171550160682")]])
    )
    await db.users.update_one({"user_id": user_id}, {"$set": {"state": "waiting_for_campaign_title"}})

async def handle_campaign_creation_states(client, message, state):
    user_id = message.from_user.id
    
    if state == "waiting_for_campaign_title":
        title = message.text.strip()
        if len(title) > 100:
            title = title[:97] + "..."
            
        # Get all connected channels to set as default force-join (only the first channel by default)
        channels = await db.get_creator_channels(user_id)
        default_fj = [channels[0]['channel_id']] if channels else []
        
        campaign_drafts[user_id] = {
            "title": title, 
            "requirements": {"force_join": default_fj, "request_join": [], "referrals": 0},
            "content_type": "upload"
        }
        await db.users.update_one({"user_id": user_id}, {"$set": {"state": "waiting_for_campaign_material"}})
        
        text = (
            "![✅](tg://emoji?id=5219899949281453881) Title set to: **{title}**\n\n"
            "![📦](tg://emoji?id=6024106569430472546) **Step 2: Send the Material**\n\n"
            "Forward or upload the content you want to lock (Image, Video, Text, Document, etc.)."
        )
        buttons = [
            [InlineKeyboardButton("Cancel", callback_data="creator_dashboard", icon_custom_emoji_id="5807651380332076999")]
        ]
        await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif state == "waiting_for_campaign_material":
        draft = campaign_drafts.get(user_id)
        if not draft:
            await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Session expired. Please start again.")
            return

        # Handle different material types
        if message.text:
            draft["material"] = {"type": "text", "content": message.text}
        elif message.photo:
            draft["material"] = {"type": "photo", "file_id": message.photo.file_id, "caption": message.caption}
        elif message.video:
            draft["material"] = {"type": "video", "file_id": message.video.file_id, "caption": message.caption}
        elif message.document:
            draft["material"] = {"type": "document", "file_id": message.document.file_id, "caption": message.caption}
        elif message.animation:
            draft["material"] = {"type": "animation", "file_id": message.animation.file_id, "caption": message.caption}
        else:
            await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Unsupported material type. Please send text, photo, video, or document.")
            return

        await db.users.update_one({"user_id": user_id}, {"$set": {"state": None}})
        await show_requirement_settings(client, message, user_id)

async def show_requirement_settings(client, message, user_id):
    draft = campaign_drafts.get(user_id)
    if not draft:
        return
        
    fj_channels = draft['requirements'].get('force_join', [])
    request_channels = draft['requirements'].get('request_join', [])
    channel_names = []
    for ch_id in fj_channels:
        channel_info = await db.get_channel(ch_id)
        style = "Request" if ch_id in request_channels else "Normal"
        if channel_info:
            channel_names.append(f"{channel_info['title']} ({style})")
        else:
            channel_names.append(f"ID: {ch_id} ({style})")
            
    channels_str = ", ".join(channel_names) if channel_names else "None"
    required_refs = draft['requirements'].get('referrals', 0)
        
    text = (
        f"![🎯](tg://emoji?id=6025879072368761539) **Campaign:** {draft['title']}\n"
        "──────────────────────\n"
        "![🛠](tg://emoji?id=6021401276904905698) **Step 3: Setup Requirements**\n\n"
        "Configure what users must do to unlock your content.\n\n"
        f"![📢](tg://emoji?id=6021726637857446455) **Force Subscribe:** `{channels_str}`\n"
        f"![👥](tg://emoji?id=6021642336239360403) **Referrals Required:** `{required_refs}`"
    )
    
    # We'll use callback buttons to toggle requirements
    buttons = [
        [InlineKeyboardButton("Choose Channel Force Subscribe", callback_data="ctf_0", icon_custom_emoji_id="6021726637857446455")],
        [InlineKeyboardButton("Set Referral Requirement", callback_data="csr", icon_custom_emoji_id="6021642336239360403")],
        [InlineKeyboardButton("Finish & Create", callback_data="cf", icon_custom_emoji_id="5219899949281453881")],
        [InlineKeyboardButton("Back", callback_data="creator_dashboard", icon_custom_emoji_id="5985574171550160682")]
    ]
    
    # Check if the message is from the bot (to edit it) or from the user (to reply)
    is_from_bot = getattr(message.from_user, "is_self", False) if message.from_user else False

    if is_from_bot:
        await message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^ctf_(\d+)$"))
async def camp_toggle_fj_handler(client, callback_query):
    page = int(callback_query.data.split("_")[1])
    user_id = callback_query.from_user.id
    channels = await db.get_creator_channels(user_id)
    draft = campaign_drafts.get(user_id)
    
    if not draft:
        await callback_query.answer("❌ Session expired.")
        return

    # Pagination Logic
    PER_PAGE = 5
    total_pages = (len(channels) + PER_PAGE - 1) // PER_PAGE
    start = page * PER_PAGE
    current_channels = channels[start:start+PER_PAGE]

    text = (
        "![📢](tg://emoji?id=6021726637857446455) **Select Channels for Force Join:**\n"
        "──────────────────────\n"
        f"![📖](tg://emoji?id=6021526054294788288) **Page:** `{page + 1}` **of** `{total_pages}`\n\n"
        "Toggle channels below. If a channel is selected, you can also toggle between Normal Link and Request Link styles."
    )
    
    buttons = []
    selected_channels = draft['requirements'].get('force_join', [])
    request_channels = draft['requirements'].get('request_join', [])
    for ch in current_channels:
        ch_id = ch['channel_id']
        is_selected = ch_id in selected_channels
        is_public = bool(ch.get('username'))
        type_str = "Public" if is_public else "Private"
        row = []
        if is_selected:
            row.append(InlineKeyboardButton(f"{ch['title']} ({type_str})", callback_data=f"tch_{ch_id}_{page}", icon_custom_emoji_id="5219899949281453881"))
            if is_public:
                row.append(InlineKeyboardButton("Public Channel", callback_data=f"pubalert_{ch_id}_{page}", icon_custom_emoji_id="5807928135139728476"))
            else:
                is_req = ch_id in request_channels
                if is_req:
                    row.append(InlineKeyboardButton("Request", callback_data=f"tlt_{ch_id}_{page}", icon_custom_emoji_id="5807557921843715576"))
                else:
                    row.append(InlineKeyboardButton("Normal", callback_data=f"tlt_{ch_id}_{page}", icon_custom_emoji_id="5807453545548487345"))
        else:
            row.append(InlineKeyboardButton(f"{ch['title']} ({type_str})", callback_data=f"tch_{ch_id}_{page}", icon_custom_emoji_id="5807651380332076999"))
            
        buttons.append(row)
    
    # Navigation Buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("Prev", callback_data=f"ctf_{page - 1}", icon_custom_emoji_id="5985574171550160682"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Next", callback_data=f"ctf_{page + 1}", icon_custom_emoji_id="5807453545548487345"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
        
    buttons.append([InlineKeyboardButton("Done", callback_data="crm", icon_custom_emoji_id="5985574171550160682")])
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^tch_(-?\d+)_(\d+)$"))
async def toggle_ch_handler(client, callback_query):
    user_id = callback_query.from_user.id
    data = callback_query.data.split("_")
    channel_id = int(data[1])
    page = int(data[2])
    draft = campaign_drafts.get(user_id)
    
    if not draft:
        await callback_query.answer("❌ Session expired.")
        return

    if "request_join" not in draft['requirements']:
        draft['requirements']['request_join'] = []

    if channel_id in draft['requirements']['force_join']:
        draft['requirements']['force_join'].remove(channel_id)
        if channel_id in draft['requirements']['request_join']:
            draft['requirements']['request_join'].remove(channel_id)
    else:
        draft['requirements']['force_join'].append(channel_id)
    
    # Refresh the same page
    callback_query.data = f"ctf_{page}"
    await camp_toggle_fj_handler(client, callback_query)

@Client.on_callback_query(filters.regex(r"^tlt_(-?\d+)_(\d+)$"))
async def toggle_link_type_handler(client, callback_query):
    user_id = callback_query.from_user.id
    data = callback_query.data.split("_")
    channel_id = int(data[1])
    page = int(data[2])
    draft = campaign_drafts.get(user_id)
    
    if not draft:
        await callback_query.answer("❌ Session expired.")
        return

    if "request_join" not in draft['requirements']:
        draft['requirements']['request_join'] = []

    if channel_id in draft['requirements']['request_join']:
        draft['requirements']['request_join'].remove(channel_id)
        await callback_query.answer("🔗 Switched to Normal Link style.", show_alert=False)
    else:
        draft['requirements']['request_join'].append(channel_id)
        await callback_query.answer("📥 Switched to Join Request Link style.", show_alert=False)

    # Refresh the same page
    callback_query.data = f"ctf_{page}"
    await camp_toggle_fj_handler(client, callback_query)

@Client.on_callback_query(filters.regex(r"^pubalert_(-?\d+)_(\d+)$"))
async def pub_channel_alert_handler(client, callback_query):
    await callback_query.answer("⚠️ Join requests are only applicable for private channels!", show_alert=True)

@Client.on_callback_query(filters.regex(r"^crm$"))
async def camp_req_menu_handler(client, callback_query):
    await show_requirement_settings(client, callback_query.message, callback_query.from_user.id)

@Client.on_callback_query(filters.regex(r"^csr$"))
async def camp_set_ref_prompt(client, callback_query):
    user_id = callback_query.from_user.id
    draft = campaign_drafts.get(user_id)
    if draft:
        draft["prompt_message_id"] = callback_query.message.id
        
    await callback_query.message.edit_text(
        "![👥](tg://emoji?id=6021642336239360403) **Set Referral Requirement**\n\n"
        "How many users should the person refer to unlock this content?\n"
        "Send 0 to disable.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="crm", icon_custom_emoji_id="5985574171550160682")]])
    )
    await db.users.update_one({"user_id": user_id}, {"$set": {"state": "waiting_for_campaign_ref"}})

# We need to add this to the handle_text_states in creator.py later or handle it here
# For now, let's assume creator.py handles it

@Client.on_callback_query(filters.regex(r"^cf$"))
async def camp_finish_handler(client, callback_query):
    user_id = callback_query.from_user.id
    draft = campaign_drafts.get(user_id)
    
    if not draft:
        await callback_query.answer("❌ Session expired.")
        return

    # Save to DB
    campaign_id = await db.create_campaign(user_id, draft)
    
    # Generate Link
    bot_username = (await client.get_me()).username
    link = f"https://t.me/{bot_username}?start={campaign_id}"
    
    fj_channels = draft['requirements'].get('force_join', [])
    channel_names = []
    for ch_id in fj_channels:
        channel_info = await db.get_channel(ch_id)
        if channel_info:
            channel_names.append(channel_info['title'])
        else:
            channel_names.append(f"ID: {ch_id}")
            
    channels_str = ", ".join(channel_names) if channel_names else "None"
    
    text = (
        "![✅](tg://emoji?id=5219899949281453881) **Campaign Created Successfully!**\n"
        "──────────────────────\n"
        f"![🎯](tg://emoji?id=6025879072368761539) **Title:** {draft['title']}\n"
        f"![📢](tg://emoji?id=6021726637857446455) **Force Join:** `{channels_str}`\n"
        f"![👥](tg://emoji?id=6021642336239360403) **Referrals Required:** {draft['requirements']['referrals']}\n\n"
        f"![🔗](tg://emoji?id=5807453545548487345) **Your Unlock Link:**\n`{link}`\n\n"
        "Share this link with your audience!"
    )
    buttons = [
        [InlineKeyboardButton("Share Link", url=f"https://t.me/share/url?url={link}", icon_custom_emoji_id="5807453545548487345")],
        [InlineKeyboardButton("Dashboard", callback_data="creator_dashboard", icon_custom_emoji_id="6026121742315952530")]
    ]
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    del campaign_drafts[user_id]

@Client.on_callback_query(filters.regex(r"^my_materials$"))
async def my_materials_handler(client, callback_query):
    user_id = callback_query.from_user.id
    campaigns = await db.get_creator_campaigns(user_id)
    
    if not campaigns:
        text = "![🛑](tg://emoji?id=6028583295447472629) No materials found. Create a campaign first."
    else:
        text = "![📦](tg://emoji?id=6024106569430472546) **Your Campaign Materials:**\n\n"
        for i, camp in enumerate(campaigns, 1):
            m_type = camp['material']['type'].capitalize()
            text += f"{i}. **{camp['title']}** ({m_type})\n"
    
    buttons = [[InlineKeyboardButton("Back", callback_data="creator_dashboard", icon_custom_emoji_id="5985574171550160682")]]
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^share_links$|^sl_(\d+)$"))
async def share_links_handler(client, callback_query):
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    # Parse page number
    if data == "share_links":
        page = 0
    else:
        page = int(data.split("_")[1])
        
    campaigns = await db.get_creator_campaigns(user_id)
    bot_username = (await client.get_me()).username
    
    if not campaigns:
        text = "![🛑](tg://emoji?id=6028583295447472629) You haven't created any campaigns yet."
        buttons = [
            [InlineKeyboardButton("Create New", callback_data="new_campaign", icon_custom_emoji_id="5807718484901108517")],
            [InlineKeyboardButton("Back", callback_data="creator_dashboard", icon_custom_emoji_id="5985574171550160682")]
        ]
        await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return

    # Pagination Logic
    PER_PAGE = 3  # Perfect size to fit links and quick-share buttons comfortably
    total_pages = (len(campaigns) + PER_PAGE - 1) // PER_PAGE
    if page >= total_pages:
        page = max(0, total_pages - 1)
        
    start = page * PER_PAGE
    current_campaigns = campaigns[start:start+PER_PAGE]
    
    text = (
        "![🔗](tg://emoji?id=5807453545548487345) **Your Campaign Share Links**\n"
        "──────────────────────\n"
        f"![📖](tg://emoji?id=6021526054294788288) **Page:** `{page + 1}` **of** `{total_pages}`\n\n"
    )
    
    buttons = []
    for i, camp in enumerate(current_campaigns, 1):
        link = f"https://t.me/{bot_username}?start={camp['_id']}"
        text += f"{start + i}. **{camp['title']}**\n`{link}`\n\n"
        # Add native sharing button
        buttons.append([InlineKeyboardButton(f"Share: {camp['title']}", url=f"https://t.me/share/url?url={link}", icon_custom_emoji_id="5807453545548487345")])
        
    # Navigation Buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("Prev", callback_data=f"sl_{page - 1}", icon_custom_emoji_id="5985574171550160682"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Next", callback_data=f"sl_{page + 1}", icon_custom_emoji_id="5807453545548487345"))
        
    if nav_buttons:
        buttons.append(nav_buttons)
        
    buttons.append([InlineKeyboardButton("Back to Dashboard", callback_data="creator_dashboard", icon_custom_emoji_id="5985574171550160682")])
    
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

