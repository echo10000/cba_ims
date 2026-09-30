def navigation(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    
    menu = []
    
    menu.append({
        'name': 'Dashboard',
        'url_name': 'dashboard',
        'icon': 'bi-speedometer2',
    })
    
    if getattr(user, 'is_admin', False):
        menu.append({
            'name': 'Users Management',
            'url_name': 'user_list',
            'icon': 'bi-people',
        })
        
    return {
        'nav_menu': menu,
    }

