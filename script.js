async function fetchData() {
    const options = {
        method: 'GET',
        headers: {
            'PanMediaAPI-Key': AIzaSyBJs9bOk3GMK1PFgpwry2Qf60omT_Yzvjs
            ,'PanMediaAPI-Host': PanMedia
        }
    }

    const res = await fetch('https://www.youtube.com'), ('https://www.tiktok.com'), ('https://www.instagram.com'), ('https://www.facebook.com'), ('https://www.twitter.com')
    const record = await res.jason()

    console.log('record', record)
}